"""
AI Hub Data Loader - Imports news articles from AI Hub JSON files into PostgreSQL.

Generates OpenAI embeddings (text-embedding-3-small) before inserting.

Usage:
    python -m app.services.data_loader              # Load sample (10,000 articles)
    python -m app.services.data_loader --full        # Load all articles
    python -m app.services.data_loader --sample 5000 # Load custom sample size
    python -m app.services.data_loader --no-embed    # Skip embedding generation
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import date
from pathlib import Path
from typing import Iterator

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.db.base import SessionLocal, engine
from app.db.models import Base, NewsArticle

logger = logging.getLogger(__name__)

DATA_DIR = settings.DATA_DIR
DEFAULT_SAMPLE_SIZE = 10_000
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 100  # OpenAI allows up to 2048 inputs per request


def _get_openai_client():
    """Lazy-load OpenAI client."""
    from openai import OpenAI

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set. Add it to .env")
    return OpenAI(api_key=api_key)


def _parse_date(raw: int | str | None) -> date | None:
    """Convert AI Hub date (YYYYMMDD int) to Python date."""
    if raw is None:
        return None
    s = str(raw).strip()
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return None


def _iter_articles(file_path: Path) -> Iterator[dict]:
    """Yield article dicts from a single AI Hub JSON file.

    Handles trailing-comma JSON by falling back to a lenient parse.
    """
    logger.info(f"Reading {file_path.name} ({file_path.stat().st_size / 1024 / 1024:.1f} MB)")

    raw = file_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # TS_text_entailment.json has trailing comma
        raw_fixed = raw.rstrip().rstrip(",").rstrip()
        if not raw_fixed.endswith("}"):
            raw_fixed += "}"
        data = json.loads(raw_fixed)

    items = data.get("data", [])
    logger.info(f"  {file_path.name}: {len(items)} entries")

    for item in items:
        paragraphs = item.get("paragraphs", [])
        content = "\n\n".join(p.get("context", "") for p in paragraphs).strip()
        if not content:
            continue

        doc_class = item.get("doc_class", {})

        yield {
            "doc_id": str(item.get("doc_id", "")),
            "title": item.get("doc_title", ""),
            "content": content,
            "source": item.get("doc_source", None),
            "published_at": _parse_date(item.get("doc_published")),
            "category": doc_class.get("class", None) if isinstance(doc_class, dict) else None,
            "category_code": doc_class.get("code", None) if isinstance(doc_class, dict) else None,
        }


def discover_json_files() -> list[Path]:
    """Find all AI Hub JSON data files in data/."""
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        logger.error(f"No JSON files found in {DATA_DIR}")
        sys.exit(1)
    logger.info(f"Found {len(files)} JSON files in {DATA_DIR}")
    return files


def load_all_articles(files: list[Path]) -> list[dict]:
    """Load all articles from JSON files into memory."""
    all_articles = []
    seen_ids = set()

    for f in files:
        for article in _iter_articles(f):
            if article["doc_id"] not in seen_ids:
                seen_ids.add(article["doc_id"])
                all_articles.append(article)

    logger.info(f"Total unique articles: {len(all_articles)}")
    return all_articles


def sample_articles(articles: list[dict], n: int) -> list[dict]:
    """Stratified sampling by category to keep category distribution."""
    if n >= len(articles):
        return articles

    by_category: dict[str, list[dict]] = {}
    for a in articles:
        cat = a.get("category") or "unknown"
        by_category.setdefault(cat, []).append(a)

    sampled = []
    for cat, cat_articles in by_category.items():
        cat_ratio = len(cat_articles) / len(articles)
        cat_n = max(1, round(n * cat_ratio))
        sampled.extend(random.sample(cat_articles, min(cat_n, len(cat_articles))))

    random.shuffle(sampled)
    logger.info(f"Sampled {len(sampled)} articles (target: {n})")
    return sampled[:n]


def generate_embeddings(articles: list[dict]) -> list[dict]:
    """Generate OpenAI embeddings for articles and attach to each dict.

    Processes in batches of EMBEDDING_BATCH_SIZE. Embeds title + content[:500]
    to stay within token limits while capturing key information.
    """
    client = _get_openai_client()
    total = len(articles)
    logger.info(f"Generating embeddings for {total} articles (model: {EMBEDDING_MODEL})")

    for i in range(0, total, EMBEDDING_BATCH_SIZE):
        batch = articles[i : i + EMBEDDING_BATCH_SIZE]
        texts = [f"{a['title']}\n{a['content'][:500]}" for a in batch]

        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
            )
            for j, item in enumerate(response.data):
                batch[j]["embedding"] = item.embedding

            batch_num = i // EMBEDDING_BATCH_SIZE + 1
            total_batches = (total + EMBEDDING_BATCH_SIZE - 1) // EMBEDDING_BATCH_SIZE
            logger.info(f"  Embedded batch {batch_num}/{total_batches}")

        except Exception as e:
            logger.warning(f"  Embedding batch failed (index {i}): {e}. Retrying in 5s...")
            time.sleep(5)
            try:
                response = client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=texts,
                )
                for j, item in enumerate(response.data):
                    batch[j]["embedding"] = item.embedding
                logger.info(f"  Retry succeeded for batch at index {i}")
            except Exception as retry_err:
                logger.error(f"  Retry also failed: {retry_err}. Skipping batch.")
                # Articles in this batch will have no embedding (NULL in DB)

    embedded_count = sum(1 for a in articles if "embedding" in a)
    logger.info(f"Embedding complete: {embedded_count}/{total} articles")
    return articles


def insert_to_db(articles: list[dict], batch_size: int = 1000):
    """Bulk insert articles into PostgreSQL."""
    if engine is None:
        logger.error("DATABASE_URL not configured. Set it in .env")
        sys.exit(1)

    Base.metadata.create_all(engine)

    total = 0
    with SessionLocal() as db:
        for i in range(0, len(articles), batch_size):
            batch = articles[i : i + batch_size]
            stmt = (
                pg_insert(NewsArticle)
                .values(batch)
                .on_conflict_do_nothing(index_elements=["doc_id"])
            )
            result = db.execute(stmt)
            db.commit()
            total += result.rowcount
            logger.info(f"  Inserted batch {i // batch_size + 1}: {result.rowcount} new rows")

    logger.info(f"Done. Inserted {total} new articles (skipped duplicates).")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Load AI Hub news data into PostgreSQL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--full", action="store_true", help="Load all articles")
    group.add_argument("--sample", type=int, default=DEFAULT_SAMPLE_SIZE, help="Sample size")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding generation")
    args = parser.parse_args()

    files = discover_json_files()
    articles = load_all_articles(files)

    if not args.full:
        articles = sample_articles(articles, args.sample)

    if not args.no_embed:
        articles = generate_embeddings(articles)

    insert_to_db(articles)


if __name__ == "__main__":
    main()
