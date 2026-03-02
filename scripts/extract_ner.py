"""
NER + POS 분석 스크립트.

DB에서 기사를 샘플링해 카테고리별 ORG·PERSON·LOC·동사를 추출·출력한다.

실행:
    python scripts/extract_ner.py                     # 기본 3000건 샘플
    python scripts/extract_ner.py --n 10000           # 샘플 수 지정
    python scripts/extract_ner.py --all               # 전체 기사
    python scripts/extract_ner.py --category 경제      # 특정 카테고리만
    python scripts/extract_ner.py --top 20            # 상위 20개 출력
    python scripts/extract_ner.py --save              # data/ner_result.json 저장
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from app.analysis.ner_extractor import NerExtractor, NerReport
from app.core.config import settings

if not settings.DATABASE_URL:
    print("ERROR: DATABASE_URL이 설정되지 않았습니다.")
    sys.exit(1)


def fetch_articles(engine, n: int | None, category: str | None) -> list[tuple]:
    conditions = [
        "body IS NOT NULL",
        "length(body) > 100",
        "category_l2 != '포토'",
    ]
    if category:
        conditions.append(f"category_l2 = '{category}'")

    where = " AND ".join(conditions)
    order = "ORDER BY random()" if n else ""
    limit = "LIMIT :n" if n else ""

    sql = text(f"SELECT id, body, category_l2 FROM news_articles WHERE {where} {order} {limit}")
    with engine.connect() as conn:
        rows = conn.execute(sql, {"n": n} if n else {}).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def print_report(report: NerReport, top_n: int, label: str = "") -> None:
    if label:
        print(f"\n{'━'*60}")
        print(f"  {label}  ({report.total_articles:,}건)")
        print(f"{'━'*60}")

    sections = [
        ("ORG (조직·기업·기관)",    report.organizations),
        ("PERSON (인물)",          report.persons),
        ("LOC (위치·국가)",         report.locations),
        ("MISC (미분류 고유명사)",   report.misc_entities),
        ("VERB (산업 동인 동사)",    report.top_verbs),
    ]

    for title, items in sections:
        if not items:
            continue
        print(f"\n  [{title}]")
        print(f"  {'순위':>4}  {'용어':<18}  {'빈도':>6}")
        print("  " + "-" * 34)
        for i, item in enumerate(items[:top_n], 1):
            count = item.count
            print(f"  {i:>4}  {item.term:<18}  {count:>6,}")


def main():
    parser = argparse.ArgumentParser(description="NER + POS 분석")
    parser.add_argument("--n", type=int, default=3000)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--category", type=str, default=None)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--min-count", type=int, default=3)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    sample_n = None if args.all else args.n

    engine = create_engine(settings.DATABASE_URL)
    label = "전체" if sample_n is None else f"{sample_n:,}건 샘플"
    cat_label = f" / 카테고리={args.category}" if args.category else ""
    print(f"DB에서 기사 로딩 중 ({label}{cat_label})...")

    articles = fetch_articles(engine, sample_n, args.category)
    print(f"  → {len(articles):,}건 로드 완료")

    extractor = NerExtractor(top_n=args.top, min_count=args.min_count)
    print("\nNER + POS 분석 중 (kiwipiepy 형태소 분석)...")

    if args.category:
        report = extractor.analyze(articles)
        print_report(report, top_n=args.top, label=args.category)
    else:
        report = extractor.analyze_by_category(articles)
        for cat, cat_report in sorted(report.by_category.items(),
                                       key=lambda x: -x[1].total_articles):
            print_report(cat_report, top_n=args.top, label=cat)

    if args.save:
        out_path = PROJECT_ROOT / "data" / "ner_result.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        def report_to_dict(r: NerReport) -> dict:
            return {
                "total_articles": r.total_articles,
                "organizations": [{"term": e.term, "count": e.count} for e in r.organizations],
                "persons":       [{"term": e.term, "count": e.count} for e in r.persons],
                "locations":     [{"term": e.term, "count": e.count} for e in r.locations],
                "misc_entities": [{"term": e.term, "count": e.count} for e in r.misc_entities],
                "top_verbs":     [{"term": v.term, "count": v.count} for v in r.top_verbs],
            }

        if args.category:
            output = report_to_dict(report)
        else:
            output = {
                "total_articles": report.total_articles,
                "by_category": {
                    cat: report_to_dict(r)
                    for cat, r in report.by_category.items()
                },
            }

        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    main()
