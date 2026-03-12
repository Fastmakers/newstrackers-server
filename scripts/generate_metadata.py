"""
데이터셋 메타데이터 생성 스크립트

DB에 저장된 뉴스 기사의 통계 정보를 분석해 data/metadata.json 으로 저장합니다.
분석 API나 LLM 프롬프트에서 "어떤 데이터가 있는지" 참조용으로 활용합니다.

대상 테이블: news_articles (기사 원문), news_chunks (청킹+임베딩)
데이터 소스: 매일경제 2025년 (2024-12 ~ 2025-12)

실행: python scripts/generate_metadata.py  (어느 디렉터리에서도 OK)
"""

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from app.core.config import settings

if not settings.DATABASE_URL:
    print("ERROR: DATABASE_URL이 설정되지 않았습니다. .env 파일을 확인하세요.")
    sys.exit(1)

engine = create_engine(settings.DATABASE_URL)
OUTPUT_PATH = PROJECT_ROOT / "data" / "metadata.json"


def fetch_articles_overview(conn) -> dict:
    row = conn.execute(text("""
        SELECT
            COUNT(*)                                                   AS total_articles,
            COUNT(*) FILTER (WHERE summary IS NOT NULL AND summary != '') AS has_summary,
            COUNT(*) FILTER (WHERE body IS NOT NULL AND body != '')    AS has_body,
            MIN(published_at)                                          AS date_min,
            MAX(published_at)                                          AS date_max,
            ROUND(AVG(length(body)))                                   AS avg_body_len,
            MIN(length(body))                                          AS min_body_len,
            MAX(length(body))                                          AS max_body_len
        FROM news_articles
        WHERE body IS NOT NULL
    """)).fetchone()

    return {
        "total_articles": row[0],
        "has_summary": row[1],
        "has_body": row[2],
        "date_range": {
            "min": row[3].isoformat() if row[3] else None,
            "max": row[4].isoformat() if row[4] else None,
        },
        "body_length": {
            "avg": int(row[5]) if row[5] else 0,
            "min": row[6],
            "max": row[7],
        },
    }


def fetch_chunks_overview(conn) -> dict:
    row = conn.execute(text("""
        SELECT
            COUNT(*)                                              AS total_chunks,
            COUNT(*) FILTER (WHERE embedding IS NOT NULL)         AS embedded_chunks,
            COUNT(DISTINCT article_id)                            AS articles_with_chunks,
            ROUND(AVG(chunk_chars))                               AS avg_chunk_chars,
            MIN(chunk_chars)                                      AS min_chunk_chars,
            MAX(chunk_chars)                                      AS max_chunk_chars,
            MAX(chunk_no) + 1                                     AS max_chunks_per_article
        FROM news_chunks
    """)).fetchone()

    # 기사당 청크 수 분포
    chunk_dist = conn.execute(text("""
        SELECT chunk_count, COUNT(*) AS article_count
        FROM (
            SELECT article_id, COUNT(*) AS chunk_count FROM news_chunks GROUP BY article_id
        ) sub
        GROUP BY chunk_count
        ORDER BY chunk_count
        LIMIT 10
    """)).fetchall()

    return {
        "total_chunks": row[0],
        "embedded_chunks": row[1],
        "articles_with_chunks": row[2],
        "chunk_version": "v1_1000_180",
        "chunk_chars": {
            "avg": int(row[3]) if row[3] else 0,
            "min": row[4],
            "max": row[5],
        },
        "chunks_per_article_distribution": [
            {"chunks": r[0], "article_count": r[1]} for r in chunk_dist
        ],
    }


def fetch_categories(conn) -> dict:
    # L1
    l1 = conn.execute(text("""
        SELECT category_l1, COUNT(*) AS cnt,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM news_articles GROUP BY category_l1 ORDER BY cnt DESC
    """)).fetchall()

    # L2
    l2 = conn.execute(text("""
        SELECT category_l2, COUNT(*) AS cnt
        FROM news_articles
        WHERE category_l1 = '뉴스'
        GROUP BY category_l2 ORDER BY cnt DESC
    """)).fetchall()

    return {
        "l1": [{"name": r[0] or "(없음)", "count": r[1], "pct": float(r[2])} for r in l1],
        "l2_news": [{"name": r[0] or "(없음)", "count": r[1]} for r in l2],
    }


def fetch_monthly_distribution(conn) -> list[dict]:
    rows = conn.execute(text("""
        SELECT
            TO_CHAR(published_at, 'YYYY-MM') AS ym,
            COUNT(*) AS count
        FROM news_articles
        WHERE published_at IS NOT NULL
        GROUP BY ym
        ORDER BY ym
    """)).fetchall()
    return [{"year_month": r[0], "count": r[1]} for r in rows]


def fetch_body_length_buckets(conn) -> list[dict]:
    rows = conn.execute(text("""
        SELECT
            CASE
                WHEN length(body) < 300   THEN '0~299'
                WHEN length(body) < 500   THEN '300~499'
                WHEN length(body) < 1000  THEN '500~999'
                WHEN length(body) < 2000  THEN '1000~1999'
                WHEN length(body) < 5000  THEN '2000~4999'
                ELSE '5000+'
            END AS bucket,
            COUNT(*) AS count
        FROM news_articles
        WHERE body IS NOT NULL
        GROUP BY bucket
        ORDER BY MIN(length(body))
    """)).fetchall()
    return [{"range_chars": r[0], "count": r[1]} for r in rows]


def fetch_raw_json_file_count() -> dict:
    """로컬 원본 JSON 파일 수 집계."""
    base = PROJECT_ROOT / "매경뉴스2025"
    if not base.exists():
        return {}
    monthly = {}
    total = 0
    for month_dir in sorted(base.iterdir()):
        if month_dir.is_dir():
            cnt = len(list(month_dir.glob("*.json")))
            monthly[month_dir.name] = cnt
            total += cnt
    return {"total": total, "by_month": monthly}


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("DB에서 메타데이터 수집 중...")
    with engine.connect() as conn:
        metadata = {
            "generated_at": datetime.now().isoformat(),
            "data_source": "매일경제 2025년",
            "tables": ["news_articles", "news_chunks"],
            "articles": fetch_articles_overview(conn),
            "chunks": fetch_chunks_overview(conn),
            "categories": fetch_categories(conn),
            "monthly_distribution": fetch_monthly_distribution(conn),
            "body_length_distribution": fetch_body_length_buckets(conn),
            "raw_json_files": fetch_raw_json_file_count(),
        }

    OUTPUT_PATH.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"저장 완료: {OUTPUT_PATH}")

    ov = metadata["articles"]
    ch = metadata["chunks"]
    print(f"\n[기사]")
    print(f"  총 기사     : {ov['total_articles']:,}")
    print(f"  기간        : {ov['date_range']['min'][:10]} ~ {ov['date_range']['max'][:10]}")
    print(f"  평균 본문   : {ov['body_length']['avg']:,}자")
    print(f"  summary 있음: {ov['has_summary']:,}")
    print(f"\n[청크]")
    print(f"  총 청크     : {ch['total_chunks']:,}")
    print(f"  임베딩 완료 : {ch['embedded_chunks']:,}")
    print(f"  평균 길이   : {ch['chunk_chars']['avg']:,}자")
    print(f"\n[카테고리 L1]")
    for c in metadata["categories"]["l1"]:
        print(f"  {c['name']:<14} {c['count']:>8,}건  ({c['pct']}%)")
    print(f"\n[카테고리 L2 (뉴스)]")
    for c in metadata["categories"]["l2_news"]:
        print(f"  {c['name']:<12} {c['count']:>8,}건")
    raw = metadata["raw_json_files"]
    if raw:
        print(f"\n[원본 JSON 파일] 총 {raw['total']:,}개")


if __name__ == "__main__":
    main()
