"""
Phase 1-3 통합 파이프라인 스크립트.

새로 추가된 기사(또는 지정 범위)에 대해 다음 세 단계를 순차 실행한다:

    Phase 1. 데이터 품질 필터링
              TextCleaner + LexicalDiversityAnalyzer
              → 노이즈 기사(포토·단신·반복스팸) 식별 및 JSON 저장

    Phase 2. NLP 분석 (corpus 통계, 선택적)
              NgramExtractor + NerExtractor
              → data/ngrams.json, data/ner_result.json 갱신

    Phase 3. 청킹 + 임베딩 → DB 저장
              text-embedding-3-small (1536d)
              → news_chunks 테이블에 벌크 INSERT

실행 예시:
    python scripts/run_pipeline.py                  # 미처리 기사만 (증분)
    python scripts/run_pipeline.py --all            # 전체 재처리
    python scripts/run_pipeline.py --phase 1        # 노이즈 탐지만
    python scripts/run_pipeline.py --phase 3        # 청킹+임베딩만
    python scripts/run_pipeline.py --dry-run        # 실제 저장 없이 확인
    python scripts/run_pipeline.py --batch-size 100 # 임베딩 배치 크기 조정
    python scripts/run_pipeline.py --limit 1000     # 처리할 기사 수 제한
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.models import NewsChunkDB
from app.analysis.lexical_diversity import LexicalDiversityAnalyzer
from app.analysis.ngram_extractor import NgramConfig, NgramExtractor
from app.analysis.ner_extractor import NerExtractor
from app.analysis.text_cleaner import TextCleaner
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
CHUNK_SIZE = 1000       # 청크당 최대 글자 수
CHUNK_OVERLAP = 180     # 연속 청크 간 오버랩 글자 수
CHUNK_STEP = CHUNK_SIZE - CHUNK_OVERLAP   # = 820
CHUNK_VERSION = "v1_1000_180"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
MIN_CHUNK_CHARS = 50    # 이 미만 길이 청크는 버림


# ---------------------------------------------------------------------------
# 청킹
# ---------------------------------------------------------------------------

def make_chunks(title: str, body: str) -> list[tuple[int, str]]:
    """
    기사 제목+본문 → (chunk_no, chunk_text) 리스트.

    chunk_no=0: "제목: {title}\\n\\n{body[:1000]}"
    chunk_no=1+: body 슬라이딩 윈도우 (step=820)
    """
    title_prefix = f"제목: {title}\n\n" if title else ""
    chunks: list[tuple[int, str]] = []

    # chunk_no=0
    first = title_prefix + body[:CHUNK_SIZE]
    if len(first.strip()) >= MIN_CHUNK_CHARS:
        chunks.append((0, first))

    # chunk_no=1 ~
    chunk_no = 1
    start = CHUNK_STEP
    while start < len(body):
        segment = body[start: start + CHUNK_SIZE]
        if len(segment.strip()) >= MIN_CHUNK_CHARS:
            chunks.append((chunk_no, segment))
        start += CHUNK_STEP
        chunk_no += 1

    return chunks


# ---------------------------------------------------------------------------
# 임베딩
# ---------------------------------------------------------------------------

def embed_batch(texts: list[str], client) -> list[list[float]]:
    """OpenAI text-embedding-3-small로 임베딩 생성. Rate limit 대비 재시도 포함."""
    for attempt in range(3):
        try:
            resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [item.embedding for item in resp.data]
        except Exception as exc:
            if attempt == 2:
                raise
            logger.warning("임베딩 API 오류 (재시도 %d/3): %s", attempt + 1, exc)
            time.sleep(2 ** attempt)
    return []   # unreachable


# ---------------------------------------------------------------------------
# DB 유틸리티
# ---------------------------------------------------------------------------

def fetch_unprocessed_articles(
    conn, limit: int | None
) -> list[tuple[int, str, str, str]]:
    """news_chunks가 없는 기사(증분)만 가져온다. → (id, title, body, category_l2)"""
    sql = """
        SELECT a.id, a.title, a.body, a.category_l2
        FROM news_articles a
        WHERE a.body IS NOT NULL
          AND length(a.body) > 100
          AND a.category_l2 != '포토'
          AND NOT EXISTS (
              SELECT 1 FROM news_chunks c WHERE c.article_id = a.id
          )
        ORDER BY a.id
        {limit}
    """.format(limit=f"LIMIT {limit}" if limit else "")
    rows = conn.execute(text(sql)).fetchall()
    return [(r[0], r[1] or "", r[2] or "", r[3] or "") for r in rows]


def fetch_all_articles(
    conn, limit: int | None
) -> list[tuple[int, str, str, str]]:
    """전체 기사(포토 제외). --all 플래그 전용."""
    sql = """
        SELECT id, title, body, category_l2
        FROM news_articles
        WHERE body IS NOT NULL
          AND length(body) > 100
          AND category_l2 != '포토'
        ORDER BY id
        {limit}
    """.format(limit=f"LIMIT {limit}" if limit else "")
    rows = conn.execute(text(sql)).fetchall()
    return [(r[0], r[1] or "", r[2] or "", r[3] or "") for r in rows]


def bulk_insert_chunks(session: Session, rows: list[dict], dry_run: bool) -> int:
    """news_chunks 테이블에 ORM 벌크 INSERT.

    pgvector Vector 타입은 SQLAlchemy ORM을 통해야 직렬화가 보장된다.
    이미 존재하는 (article_id, chunk_no)는 DB UNIQUE 제약으로 자동 무시.
    """
    if dry_run or not rows:
        return len(rows)

    # 이미 존재하는 (article_id, chunk_version) 조합 확인 후 신규만 삽입
    article_ids = list({r["article_id"] for r in rows})
    existing = set(
        session.execute(
            text("""
                SELECT article_id, chunk_no FROM news_chunks
                WHERE article_id = ANY(:ids) AND chunk_version = :version
            """),
            {"ids": article_ids, "version": CHUNK_VERSION},
        ).fetchall()
    )

    new_objs = [
        NewsChunkDB(
            article_id=r["article_id"],
            chunk_version=r["chunk_version"],
            chunk_no=r["chunk_no"],
            chunk_text=r["chunk_text"],
            chunk_chars=r["chunk_chars"],
            chunk_tokens_est=r["chunk_tokens_est"],
            section_type=r["section_type"],
            embedding_model=r["embedding_model"],
            embedding=r["embedding"],
            created_at=r["created_at"],
        )
        for r in rows
        if (r["article_id"], r["chunk_no"]) not in existing
    ]

    if new_objs:
        session.add_all(new_objs)
        session.commit()
    return len(new_objs)


# ---------------------------------------------------------------------------
# Phase 1: 노이즈 탐지
# ---------------------------------------------------------------------------

def run_phase1(
    articles: list[tuple[int, str, str, str]],
    dry_run: bool,
) -> set[int]:
    """LexicalDiversityAnalyzer로 노이즈 기사 ID 집합 반환 + JSON 저장."""
    logger.info("[Phase 1] 노이즈 탐지 시작 — %d건", len(articles))
    cleaner = TextCleaner()
    analyzer = LexicalDiversityAnalyzer()

    # TextCleaner 적용 후 분석
    cleaned_articles = [(aid, cleaner.clean(body)) for aid, title, body, _ in articles]
    report = analyzer.analyze(cleaned_articles)

    noise_ids = set(analyzer.noise_article_ids(report))

    logger.info(
        "[Phase 1] 완료: 전체=%d  분석가능=%d  노이즈=%d (%.1f%%)",
        report.total_articles,
        report.analyzed_articles,
        report.noise_count,
        report.noise_ratio * 100,
    )

    if not dry_run:
        out_path = PROJECT_ROOT / "data" / "lexical_diversity.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "total_articles": report.total_articles,
                    "analyzed_articles": report.analyzed_articles,
                    "noise_count": report.noise_count,
                    "noise_ratio": round(report.noise_ratio, 4),
                    "log_ttr_mean": report.log_ttr_mean,
                    "log_ttr_std": report.log_ttr_std,
                    "log_ttr_p5": report.log_ttr_p5,
                    "log_ttr_p95": report.log_ttr_p95,
                    "noise_article_ids": list(noise_ids),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("[Phase 1] data/lexical_diversity.json 저장 완료")

    return noise_ids


# ---------------------------------------------------------------------------
# Phase 2: NLP 분석 (corpus 통계)
# ---------------------------------------------------------------------------

def run_phase2(
    articles: list[tuple[int, str, str, str]],
    dry_run: bool,
) -> None:
    """NgramExtractor + NerExtractor 실행 후 JSON 저장."""
    logger.info("[Phase 2] NLP 분석 시작 — %d건", len(articles))

    # (id, body, category_l2) 형태로 변환
    article_tuples = [(aid, body, cat) for aid, title, body, cat in articles]

    # N-gram TF-IDF
    ngram_cfg = NgramConfig(max_features=500, ngram_range=(1, 2), min_df=5)
    ngram_extractor = NgramExtractor(config=ngram_cfg)
    ngram_report = ngram_extractor.analyze_by_category(article_tuples)

    # NER + POS
    ner_extractor = NerExtractor(top_n=50, min_count=3)
    ner_report = ner_extractor.analyze_by_category(article_tuples)

    if not dry_run:
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # ngrams.json
        ngrams_path = data_dir / "ngrams.json"
        ngrams_path.write_text(
            json.dumps(
                {
                    "total_articles": ngram_report.total_articles,
                    "config": {
                        "max_features": ngram_cfg.max_features,
                        "ngram_range": list(ngram_cfg.ngram_range),
                        "min_df": ngram_cfg.min_df,
                    },
                    "by_category": {
                        cat: [{"keyword": kw.keyword, "score": round(kw.score, 4)} for kw in kws[:50]]
                        for cat, kws in ngram_report.by_category.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("[Phase 2] data/ngrams.json 저장 완료")

        # ner_result.json
        def report_to_dict(r):
            return {
                "total_articles": r.total_articles,
                "organizations": [{"term": e.term, "count": e.count} for e in r.organizations],
                "persons":       [{"term": e.term, "count": e.count} for e in r.persons],
                "locations":     [{"term": e.term, "count": e.count} for e in r.locations],
                "top_verbs":     [{"term": v.term, "count": v.count} for v in r.top_verbs],
            }

        ner_path = data_dir / "ner_result.json"
        ner_path.write_text(
            json.dumps(
                {
                    "total_articles": ner_report.total_articles,
                    "by_category": {
                        cat: report_to_dict(r)
                        for cat, r in ner_report.by_category.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("[Phase 2] data/ner_result.json 저장 완료")


# ---------------------------------------------------------------------------
# Phase 3: 청킹 + 임베딩 + DB 저장
# ---------------------------------------------------------------------------

def run_phase3(
    articles: list[tuple[int, str, str, str]],
    noise_ids: set[int],
    session: Session,
    batch_size: int,
    dry_run: bool,
) -> None:
    """비노이즈 기사를 청킹하고 임베딩 후 news_chunks에 저장."""
    from openai import OpenAI

    if not settings.OPENAI_API_KEY:
        logger.error("[Phase 3] OPENAI_API_KEY가 설정되지 않았습니다.")
        return

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    cleaner = TextCleaner()

    valid_articles = [(aid, title, body, cat) for aid, title, body, cat in articles
                      if aid not in noise_ids]

    logger.info(
        "[Phase 3] 청킹+임베딩 시작 — %d건 (노이즈 %d건 제외)",
        len(valid_articles),
        len(noise_ids),
    )

    # 전체 청크를 배치 단위로 처리
    chunk_buffer: list[tuple[int, int, str]] = []  # (article_id, chunk_no, chunk_text)
    total_inserted = 0
    now = datetime.now(timezone.utc)

    def flush_buffer(buf: list[tuple[int, int, str]]) -> int:
        texts = [t for _, _, t in buf]
        embeddings = embed_batch(texts, client)
        rows = [
            {
                "article_id": article_id,
                "chunk_version": CHUNK_VERSION,
                "chunk_no": chunk_no,
                "chunk_text": chunk_text,
                "chunk_chars": len(chunk_text),
                "chunk_tokens_est": len(chunk_text) // 4,  # 대략 4자/토큰
                "section_type": "body",
                "embedding_model": EMBEDDING_MODEL,
                "embedding": emb,        # list[float] → pgvector Vector (ORM이 직렬화)
                "created_at": now,
            }
            for (article_id, chunk_no, chunk_text), emb in zip(buf, embeddings)
        ]
        return bulk_insert_chunks(session, rows, dry_run)

    for i, (aid, title, body, _) in enumerate(valid_articles, 1):
        clean_body = cleaner.clean(body)
        chunks = make_chunks(title, clean_body)
        for chunk_no, chunk_text in chunks:
            chunk_buffer.append((aid, chunk_no, chunk_text))

        # 배치 사이즈 도달 시 플러시
        if len(chunk_buffer) >= batch_size:
            inserted = flush_buffer(chunk_buffer)
            total_inserted += inserted
            chunk_buffer = []
            logger.info(
                "[Phase 3] 진행: %d/%d 기사 처리 완료, 누적 청크 %d건",
                i, len(valid_articles), total_inserted,
            )

    # 잔여 버퍼 처리
    if chunk_buffer:
        inserted = flush_buffer(chunk_buffer)
        total_inserted += inserted

    logger.info("[Phase 3] 완료 — 총 %d개 청크 저장", total_inserted)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Phase 1-3 통합 파이프라인")
    parser.add_argument("--all", action="store_true", help="전체 기사 재처리 (기본: 미처리 기사만)")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], default=None,
                        help="특정 Phase만 실행 (기본: 전체)")
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 기사 수")
    parser.add_argument("--batch-size", type=int, default=200,
                        help="임베딩 API 배치 크기 (기본 200)")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 DB/파일 저장 없이 실행 확인만")
    args = parser.parse_args()

    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL이 설정되지 않았습니다.")
        sys.exit(1)

    engine = create_engine(settings.DATABASE_URL)

    # 처리 대상 기사 로드
    with engine.connect() as conn:
        if args.all:
            articles = fetch_all_articles(conn, args.limit)
        else:
            articles = fetch_unprocessed_articles(conn, args.limit)

    logger.info("처리 대상 기사: %d건 (dry_run=%s)", len(articles), args.dry_run)

    if not articles:
        logger.info("처리할 기사가 없습니다. (모두 이미 임베딩 완료)")
        return

    run_all = args.phase is None
    noise_ids: set[int] = set()

    # Phase 1
    if run_all or args.phase == 1:
        noise_ids = run_phase1(articles, dry_run=args.dry_run)
    else:
        # Phase 3만 실행하는 경우 저장된 JSON에서 노이즈 ID 로드
        noise_json = PROJECT_ROOT / "data" / "lexical_diversity.json"
        if noise_json.exists():
            noise_ids = set(json.loads(noise_json.read_text())["noise_article_ids"])
            logger.info("기존 noise_article_ids 로드: %d건", len(noise_ids))

    # Phase 2
    if run_all or args.phase == 2:
        valid = [(aid, t, b, c) for aid, t, b, c in articles if aid not in noise_ids]
        run_phase2(valid, dry_run=args.dry_run)

    # Phase 3
    if run_all or args.phase == 3:
        with Session(engine) as session:
            run_phase3(
                articles=articles,
                noise_ids=noise_ids,
                session=session,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )

    logger.info("파이프라인 완료.")


if __name__ == "__main__":
    main()
