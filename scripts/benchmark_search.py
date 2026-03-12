#!/usr/bin/env python3
"""
scripts/benchmark_search.py — 검색 파이프라인 성능 벤치마크.

명세서: docs/04_benchmark_spec.md

실험 구성:
  E1: 직렬 + ILIKE   (베이스라인)
  E2: 병렬 + ILIKE
  E3: 직렬 + pg_trgm
  E4: 병렬 + pg_trgm (현재 기본값)

실행:
  python scripts/benchmark_search.py
  python scripts/benchmark_search.py --repeat 10 --save
  python scripts/benchmark_search.py --queries "삼성전자" "현대차" --repeat 5
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ─── 기본 테스트 쿼리 (docs/04_benchmark_spec.md §2-2) ──────────────────────
DEFAULT_QUERIES = [
    "반도체 HBM 삼성 SK하이닉스",
    "금리 인상 물가 기준금리 한국은행",
    "전기차 배터리 충전 인프라 보조금",
]


# ─── 실험별 검색 함수 ────────────────────────────────────────────────────────

def _run_e1_serial_ilike(news_service, query: str, top_k: int) -> list:
    """E1: 직렬 + ILIKE (베이스라인)."""
    from concurrent.futures import ThreadPoolExecutor

    from app.db.adapters.news_adapter import article_row_to_domain, chunk_row_to_domain
    from app.db.repositories.news_repository import NewsRepository
    from app.services.search.rrf import rrf_fuse

    embedding = news_service.embed_query(query)
    with news_service._repo() as db:
        repo = NewsRepository(db)
        vector_pairs = repo.search_chunks_by_vector(embedding, None, limit=100)
        keyword_pairs = repo.search_chunks_by_keyword_ilike(query, None, limit=100)

        vector_chunks = [chunk_row_to_domain(c, article_row_to_domain(a)) for c, a in vector_pairs]
        keyword_chunks = [chunk_row_to_domain(c, article_row_to_domain(a)) for c, a in keyword_pairs]

    fused = rrf_fuse(vector_chunks, keyword_chunks, top_n=100)
    return news_service._dedup(fused, top_k)


def _run_e2_parallel_ilike(news_service, query: str, top_k: int) -> list:
    """E2: 병렬 + ILIKE."""
    from concurrent.futures import ThreadPoolExecutor

    from app.db.adapters.news_adapter import article_row_to_domain, chunk_row_to_domain
    from app.db.repositories.news_repository import NewsRepository
    from app.services.search.rrf import rrf_fuse

    def _kw_ilike(q, cat):
        with news_service._repo() as db:
            pairs = NewsRepository(db).search_chunks_by_keyword_ilike(q, cat, limit=100)
            return [chunk_row_to_domain(c, article_row_to_domain(a)) for c, a in pairs]

    with ThreadPoolExecutor(max_workers=3) as ex:
        future_embed = ex.submit(news_service.embed_query, query)
        future_kw = ex.submit(_kw_ilike, query, None)

        embedding = future_embed.result()
        future_vec = ex.submit(news_service._vector_search_chunks, embedding, None)

        keyword_chunks = future_kw.result()
        vector_chunks = future_vec.result()

    fused = rrf_fuse(vector_chunks, keyword_chunks, top_n=100)
    return news_service._dedup(fused, top_k)


def _run_e3_serial_trgm(news_service, query: str, top_k: int) -> list:
    """E3: 직렬 + pg_trgm."""
    from app.services.search.rrf import rrf_fuse

    embedding = news_service.embed_query(query)
    keyword_chunks = news_service._keyword_search_chunks(query, None)
    vector_chunks = news_service._vector_search_chunks(embedding, None)

    fused = rrf_fuse(vector_chunks, keyword_chunks, top_n=100)
    return news_service._dedup(fused, top_k)


def _run_e4_parallel_trgm(news_service, query: str, top_k: int) -> list:
    """E4: 병렬 + pg_trgm (현재 기본값)."""
    return news_service.hybrid_search(query, top_k=top_k)


# ─── 측정 유틸 ───────────────────────────────────────────────────────────────

def _measure(fn, *args, repeat: int = 5) -> dict:
    """fn(*args)를 repeat+1회 실행, 첫 warm-up 제외 후 통계 반환."""
    times = []
    result_count = 0
    for i in range(repeat + 1):
        start = time.perf_counter()
        try:
            result = fn(*args)
            result_count = len(result)
        except Exception as exc:
            return {"error": str(exc), "mean_ms": None, "p50_ms": None, "p95_ms": None, "count": 0}
        elapsed_ms = (time.perf_counter() - start) * 1000
        if i > 0:  # warm-up 제외
            times.append(elapsed_ms)

    sorted_times = sorted(times)
    p95_idx = max(0, int(len(sorted_times) * 0.95) - 1)
    return {
        "mean_ms": statistics.mean(times),
        "p50_ms": statistics.median(times),
        "p95_ms": sorted_times[p95_idx],
        "count": result_count,
        "raw_ms": times,
    }


# ─── 출력 유틸 ───────────────────────────────────────────────────────────────

def _pct(base: float | None, cur: float | None) -> str:
    if base is None or cur is None or base == 0:
        return ""
    pct = (cur - base) / base * 100
    sign = "+" if pct > 0 else ""
    return f"  ({sign}{pct:.0f}%)"


def _print_results(experiments: list[dict], queries: list[str], repeat: int):
    sep = "=" * 68
    print(f"\n{sep}")
    print("  뉴스 검색 파이프라인 성능 벤치마크")
    print(f"{sep}")
    print(f"반복: {repeat}회 (warm-up 1회 제외)  |  쿼리: {len(queries)}개\n")
    print("테스트 쿼리:")
    for i, q in enumerate(queries, 1):
        print(f"  [Q{i}] {q}")
    print(f"\n{sep}")
    print(f"{'실험':<30}  {'평균(ms)':>8}  {'P50(ms)':>8}  {'P95(ms)':>8}  {'결과수':>6}")
    print("-" * 68)

    e1_mean = None
    for exp in experiments:
        name = exp["name"]
        stats = exp["stats"]  # averaged across queries
        mean_ms = stats.get("mean_ms")
        p50_ms = stats.get("p50_ms")
        p95_ms = stats.get("p95_ms")
        count = stats.get("count", 0)
        error = stats.get("error")

        if error:
            print(f"{name:<30}  [오류] {error}")
            continue

        pct_str = _pct(e1_mean, mean_ms) if exp["id"] != "E1" else ""
        print(
            f"{name:<30}  {mean_ms:>8.0f}  {p50_ms:>8.0f}  {p95_ms:>8.0f}  {count:>6}{pct_str}"
        )
        if exp["id"] == "E1":
            e1_mean = mean_ms

    print(f"{sep}\n")

    # 기여도 분해
    e1 = next((e for e in experiments if e["id"] == "E1"), None)
    e2 = next((e for e in experiments if e["id"] == "E2"), None)
    e3 = next((e for e in experiments if e["id"] == "E3"), None)
    e4 = next((e for e in experiments if e["id"] == "E4"), None)

    if all(e and e["stats"].get("mean_ms") for e in [e1, e2, e3, e4]):
        b = e1["stats"]["mean_ms"]
        print("최적화 기여도 분해:")
        print(f"  병렬화 단독 효과   : {e2['stats']['mean_ms']-b:+.0f}ms  ({_pct(b, e2['stats']['mean_ms']).strip()})")
        print(f"  pg_trgm 단독 효과  : {e3['stats']['mean_ms']-b:+.0f}ms  ({_pct(b, e3['stats']['mean_ms']).strip()})")
        print(f"  복합 (E4 현재)     : {e4['stats']['mean_ms']-b:+.0f}ms  ({_pct(b, e4['stats']['mean_ms']).strip()})")
        print(f"{sep}\n")


# ─── 메인 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="검색 파이프라인 성능 벤치마크")
    parser.add_argument("--repeat", type=int, default=5, help="반복 횟수 (warm-up 제외, 기본 5)")
    parser.add_argument("--queries", nargs="+", default=None, help="테스트 쿼리 (기본: 명세서 3개)")
    parser.add_argument("--top-k", type=int, default=10, help="검색 결과 수 (기본 10)")
    parser.add_argument("--save", action="store_true", help="결과를 data/benchmark_results.json에 저장")
    args = parser.parse_args()

    queries = args.queries or DEFAULT_QUERIES
    top_k = args.top_k
    repeat = args.repeat

    print("서비스 초기화 중...")
    from app.services.news_service import NewsService
    news_service = NewsService()

    EXPERIMENTS = [
        {"id": "E1", "name": "E1: 직렬 + ILIKE (베이스라인)", "fn": _run_e1_serial_ilike},
        {"id": "E2", "name": "E2: 병렬 + ILIKE",              "fn": _run_e2_parallel_ilike},
        {"id": "E3", "name": "E3: 직렬 + pg_trgm",           "fn": _run_e3_serial_trgm},
        {"id": "E4", "name": "E4: 병렬 + pg_trgm (현재)",    "fn": _run_e4_parallel_trgm},
    ]

    results = []
    for exp in EXPERIMENTS:
        print(f"  실행 중: {exp['name']} ...", end=" ", flush=True)

        # 쿼리별 측정 후 평균 집계
        all_means, all_p50s, all_p95s, all_counts = [], [], [], []
        last_error = None

        for q in queries:
            r = _measure(exp["fn"], news_service, q, top_k, repeat=repeat)
            if r.get("error"):
                last_error = r["error"]
                break
            all_means.append(r["mean_ms"])
            all_p50s.append(r["p50_ms"])
            all_p95s.append(r["p95_ms"])
            all_counts.append(r["count"])

        if last_error:
            agg_stats = {"error": last_error}
        else:
            agg_stats = {
                "mean_ms": statistics.mean(all_means),
                "p50_ms": statistics.mean(all_p50s),
                "p95_ms": statistics.mean(all_p95s),
                "count": int(statistics.mean(all_counts)),
            }
        results.append({"id": exp["id"], "name": exp["name"], "stats": agg_stats})
        print("완료" if not last_error else f"오류: {last_error}")

    _print_results(results, queries, repeat)

    if args.save:
        out = {
            "queries": queries,
            "repeat": repeat,
            "top_k": top_k,
            "experiments": results,
        }
        save_path = PROJECT_ROOT / "data" / "benchmark_results.json"
        save_path.parent.mkdir(exist_ok=True)
        save_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"결과 저장: {save_path}")


if __name__ == "__main__":
    main()
