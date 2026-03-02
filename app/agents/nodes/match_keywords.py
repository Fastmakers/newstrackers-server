import asyncio
import re
import time

from app.agents.state import AnalysisState
from app.services.vector_store import vector_store_service


def _keyword_tokens(text: str) -> list[str]:
    """한글/영문/숫자 토큰 추출 (짧은 토큰 제거)."""
    return [t for t in re.findall(r"[0-9A-Za-z가-힣]+", text) if len(t) >= 2]


def _relevance_bonus(news: dict, profile: dict) -> float:
    """
    프로필 키워드와 뉴스 메타/본문의 단순 매칭 보너스.
    최종 정렬은 distance + bonus를 함께 사용.
    """
    metadata = news.get("metadata") or {}
    haystack = " ".join(
        [
            str(metadata.get("title") or ""),
            str(metadata.get("job_category") or ""),
            str(news.get("document") or "")[:800],  # 비용 절감을 위해 앞부분만 사용
        ]
    ).lower()

    bonus = 0.0
    industry = (profile.get("industry") or "").strip()
    company = (profile.get("company") or "").strip()
    job_title = (profile.get("job_title") or "").strip()

    if industry and industry.lower() in haystack:
        bonus += 0.12
    if company and company.lower() in haystack:
        bonus += 0.12

    for token in _keyword_tokens(job_title)[:4]:
        if token.lower() in haystack:
            bonus += 0.04

    for skill in (profile.get("skills") or [])[:3]:
        token = str(skill).strip().lower()
        if token and token in haystack:
            bonus += 0.03

    return bonus


async def match_keywords(state: AnalysisState) -> AnalysisState:
    """
    Node 2: 키워드 매칭

    자소서 분석 결과를 바탕으로 pgvector에서 관련 뉴스를 검색합니다.
    여러 쿼리를 병렬로 검색하고 중복 제거 후 유사도 순으로 정렬합니다.
    """
    if state.get("error"):
        return state
    started_at = time.perf_counter()
    timings = dict(state.get("node_timings_ms") or {})

    profile = state["resume_profile"]
    industry = profile["industry"]
    job_title = profile["job_title"]
    company = profile["company"]
    skills = profile["skills"]

    # 검색 쿼리 구성: 산업 + 직무/기업 조합 + 상위 스킬
    search_queries = [
        industry,
        f"{industry} {job_title}",
        f"{industry} {company} {job_title}" if company else "",
        company,
        *skills[:3],
    ]

    # chunk 단위가 아닌 article 단위 중복 제거로 다양성 확보
    seen_article_ids: set[str] = set()
    all_results: list[dict] = []

    valid_queries = [query for query in search_queries if query.strip()]
    tasks = [
        vector_store_service.search(
            query=query,
            n_results=8,
        )
        for query in valid_queries
    ]
    results_per_query = await asyncio.gather(*tasks, return_exceptions=True)

    for query, results in zip(valid_queries, results_per_query):
        if isinstance(results, Exception):
            print(f"[Node 2] 검색 실패 (query='{query}'): {results}")
            continue

        for r in results:
            article_id = str(r.get("article_id") or r["id"])
            if article_id not in seen_article_ids:
                seen_article_ids.add(article_id)
                all_results.append(r)

    # distance + 프로필 키워드 매칭 보너스로 재정렬 후 최대 15건
    all_results.sort(key=lambda x: (x["distance"] - _relevance_bonus(x, profile), x["distance"]))
    top_results = all_results[:15]

    timings["node2_match_keywords"] = round((time.perf_counter() - started_at) * 1000, 2)
    print(
        f"[Node 2] 키워드 매칭 완료: {len(top_results)}건 (쿼리 {len(valid_queries)}개, "
        f"{timings['node2_match_keywords']}ms)"
    )
    return {**state, "matched_news": top_results, "node_timings_ms": timings}
