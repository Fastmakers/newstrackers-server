"""
TF-IDF N-gram 키워드 추출 스크립트.

DB에서 기사를 로드하고 카테고리별 상위 키워드를 추출·저장한다.

실행:
    python scripts/extract_ngrams.py                    # 기본 5000건 샘플
    python scripts/extract_ngrams.py --n 20000          # 샘플 수 지정
    python scripts/extract_ngrams.py --all              # 전체 기사
    python scripts/extract_ngrams.py --category 경제     # 특정 카테고리만
    python scripts/extract_ngrams.py --bigram-only      # 바이그램만 (ngram_range=2,2)
    python scripts/extract_ngrams.py --save             # data/ngrams.json 저장
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from app.analysis.ngram_extractor import NgramConfig, NgramExtractor
from app.core.config import settings

if not settings.DATABASE_URL:
    print("ERROR: DATABASE_URL이 설정되지 않았습니다.")
    sys.exit(1)


def fetch_articles(
    engine, n: int | None, category: str | None
) -> list[tuple[int, str, str]]:
    """DB에서 (id, body, category_l2) 쌍을 가져온다."""
    conditions = [
        "body IS NOT NULL",
        "length(body) > 100",
        "category_l2 != '포토'",   # 포토 기사는 항상 제외
    ]
    if category:
        conditions.append(f"category_l2 = '{category}'")

    where = " AND ".join(conditions)
    order = "ORDER BY random()" if n else ""
    limit = f"LIMIT :n" if n else ""

    sql = text(f"SELECT id, body, category_l2 FROM news_articles WHERE {where} {order} {limit}")
    params = {"n": n} if n else {}

    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def print_keywords(keywords, top_n: int = 30, title: str = "") -> None:
    if title:
        print(f"\n  [{title}]")
    print(f"  {'순위':>4}  {'키워드':<20}  {'점수':>8}")
    print("  " + "-" * 38)
    for i, kw in enumerate(keywords[:top_n], 1):
        print(f"  {i:>4}  {kw.keyword:<20}  {kw.score:>8.2f}")


def main():
    parser = argparse.ArgumentParser(description="TF-IDF N-gram 키워드 추출")
    parser.add_argument("--n", type=int, default=5000, help="샘플링할 기사 수 (기본 5000)")
    parser.add_argument("--all", action="store_true", help="전체 기사 분석")
    parser.add_argument("--category", type=str, default=None, help="특정 카테고리만 분석")
    parser.add_argument("--bigram-only", action="store_true", help="바이그램만 추출 (1,2 → 2,2)")
    parser.add_argument("--max-features", type=int, default=1000)
    parser.add_argument("--min-df", type=int, default=5)
    parser.add_argument("--top", type=int, default=30, help="출력할 상위 키워드 수")
    parser.add_argument("--save", action="store_true", help="data/ngrams.json으로 저장")
    args = parser.parse_args()

    sample_n = None if args.all else args.n
    ngram_range = (2, 2) if args.bigram_only else (1, 2)

    cfg = NgramConfig(
        max_features=args.max_features,
        ngram_range=ngram_range,
        min_df=args.min_df,
    )

    engine = create_engine(settings.DATABASE_URL)
    label = "전체" if sample_n is None else f"{sample_n:,}건 샘플"
    cat_label = f" / 카테고리={args.category}" if args.category else ""
    print(f"DB에서 기사 로딩 중 ({label}{cat_label})...")

    articles = fetch_articles(engine, sample_n, args.category)
    print(f"  → {len(articles):,}건 로드 완료")

    extractor = NgramExtractor(config=cfg)

    print(f"\nTF-IDF N-gram 분석 중 (ngram={ngram_range}, max={cfg.max_features}, min_df={cfg.min_df})...")

    if args.category:
        # 단일 카테고리
        report = extractor.analyze(articles)
        print(f"\n{'='*60}")
        print(f"  {args.category} — 상위 키워드")
        print("="*60)
        print_keywords(report.keywords, top_n=args.top, title=args.category)
    else:
        # 전체 + 카테고리별
        report = extractor.analyze_by_category(articles)
        print(f"\n{'='*60}")
        print(f"  카테고리별 상위 {args.top}개 키워드")
        print("="*60)
        for cat, keywords in sorted(report.by_category.items(), key=lambda x: -len(x[1])):
            print_keywords(keywords, top_n=args.top, title=cat)

    # 저장
    if args.save:
        out_path = PROJECT_ROOT / "data" / "ngrams.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        output: dict = {
            "total_articles": report.total_articles,
            "config": {
                "max_features": cfg.max_features,
                "ngram_range": list(cfg.ngram_range),
                "min_df": cfg.min_df,
                "use_tfidf": cfg.use_tfidf,
            },
        }

        if args.category:
            output["keywords"] = [
                {"keyword": kw.keyword, "score": round(kw.score, 4)}
                for kw in report.keywords
            ]
        else:
            output["by_category"] = {
                cat: [
                    {"keyword": kw.keyword, "score": round(kw.score, 4)}
                    for kw in keywords[:args.top]
                ]
                for cat, keywords in report.by_category.items()
            }

        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    main()
