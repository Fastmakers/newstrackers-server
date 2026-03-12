"""
어휘 다양성 (LogTTR) 분석 스크립트.

DB의 news_articles에서 기사를 샘플링해 LogTTR을 계산하고,
분포 히스토그램과 노이즈 기사 목록을 출력한다.

실행:
    python scripts/analyze_lexical_diversity.py            # 기본 샘플 5000건
    python scripts/analyze_lexical_diversity.py --n 10000  # 샘플 수 지정
    python scripts/analyze_lexical_diversity.py --all      # 전체 기사 (느림)
    python scripts/analyze_lexical_diversity.py --save     # 결과를 JSON으로 저장
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from app.analysis.lexical_diversity import LexicalDiversityAnalyzer
from app.core.config import settings

if not settings.DATABASE_URL:
    print("ERROR: DATABASE_URL이 설정되지 않았습니다.")
    sys.exit(1)


def fetch_articles(engine, n: int | None) -> list[tuple[int, str]]:
    """DB에서 (id, body) 쌍을 가져온다."""
    if n:
        sql = text("""
            SELECT id, body FROM news_articles
            WHERE body IS NOT NULL AND length(body) > 50
            ORDER BY random()
            LIMIT :n
        """)
        params = {"n": n}
    else:
        sql = text("""
            SELECT id, body FROM news_articles
            WHERE body IS NOT NULL AND length(body) > 50
        """)
        params = {}

    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(r[0], r[1]) for r in rows]


def print_histogram(values: list[float], bins: int = 20) -> None:
    """ASCII 히스토그램 출력."""
    if not values:
        return
    min_v, max_v = min(values), max(values)
    width = (max_v - min_v) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - min_v) / width), bins - 1)
        counts[idx] += 1

    max_count = max(counts) if counts else 1
    bar_width = 40

    print(f"\n  {'LogTTR':>8}  {'빈도':>6}  {'막대':}")
    print("  " + "-" * 60)
    for i, cnt in enumerate(counts):
        lo = min_v + i * width
        hi = lo + width
        bar = "█" * int(cnt / max_count * bar_width)
        print(f"  {lo:>5.3f}~{hi:<5.3f}  {cnt:>6,}  {bar}")


def print_noise_samples(stats, n: int = 10) -> None:
    """노이즈 기사 샘플 출력."""
    noise = [s for s in stats if s.is_noise]
    if not noise:
        print("  노이즈 기사 없음")
        return
    for s in noise[:n]:
        log_ttr_str = f"{s.log_ttr:.4f}" if s.log_ttr is not None else "N/A"
        print(f"  ID={s.article_id:>8}  tokens={s.token_count:>5}  "
              f"log_ttr={log_ttr_str:>8}  {s.noise_reason}")
    if len(noise) > n:
        print(f"  ... 외 {len(noise) - n}건")


def main():
    parser = argparse.ArgumentParser(description="LogTTR 어휘 다양성 분석")
    parser.add_argument("--n", type=int, default=5000, help="샘플링할 기사 수 (기본 5000)")
    parser.add_argument("--all", action="store_true", help="전체 기사 분석")
    parser.add_argument("--save", action="store_true", help="결과를 data/lexical_diversity.json으로 저장")
    args = parser.parse_args()

    sample_n = None if args.all else args.n

    engine = create_engine(settings.DATABASE_URL)

    print(f"DB에서 기사 로딩 중 ({'전체' if sample_n is None else f'{sample_n:,}건 샘플'})...")
    articles = fetch_articles(engine, sample_n)
    print(f"  → {len(articles):,}건 로드 완료")

    analyzer = LexicalDiversityAnalyzer()
    print("\nLogTTR 계산 중 (kiwipiepy 명사 추출)...")
    report = analyzer.analyze(articles)

    # ── 요약 출력 ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  어휘 다양성 (LogTTR) 분석 결과")
    print("=" * 60)
    print(f"  총 기사       : {report.total_articles:,}건")
    print(f"  분석 가능     : {report.analyzed_articles:,}건 "
          f"(토큰 < {analyzer.min_tokens}개 제외)")
    print(f"  LogTTR 평균   : {report.log_ttr_mean:.4f}")
    print(f"  LogTTR 표준편차: {report.log_ttr_std:.4f}")
    print(f"  LogTTR p5  (하위 5%, 참고): {report.log_ttr_p5:.4f}")
    print(f"  LogTTR p95 (상위 5%, 참고): {report.log_ttr_p95:.4f}")
    print(f"  노이즈 임계값 : < {analyzer.low_threshold} (반복) / > {analyzer.high_threshold} (파싱오류)")
    print(f"  노이즈 기사   : {report.noise_count:,}건 "
          f"({report.noise_ratio * 100:.1f}%)")

    # ── 히스토그램 ────────────────────────────────────────────────────
    valid_values = [s.log_ttr for s in report.stats if s.log_ttr is not None]
    print("\n[LogTTR 분포 히스토그램]")
    print_histogram(valid_values)

    # ── 노이즈 샘플 ──────────────────────────────────────────────────
    print("\n[노이즈 기사 샘플 (상위 10건)]")
    print_noise_samples(report.stats)

    # ── 저장 ─────────────────────────────────────────────────────────
    if args.save:
        out_path = PROJECT_ROOT / "data" / "lexical_diversity.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        output = {
            "total_articles": report.total_articles,
            "analyzed_articles": report.analyzed_articles,
            "noise_count": report.noise_count,
            "noise_ratio": round(report.noise_ratio, 4),
            "log_ttr_mean": report.log_ttr_mean,
            "log_ttr_std": report.log_ttr_std,
            "log_ttr_p5": report.log_ttr_p5,
            "log_ttr_p95": report.log_ttr_p95,
            "noise_article_ids": analyzer.noise_article_ids(report),
        }
        out_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    main()
