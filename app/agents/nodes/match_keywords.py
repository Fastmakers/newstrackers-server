import asyncio

from app.agents.state import AnalysisState
from app.services.vector_store import vector_store_service


async def match_keywords(state: AnalysisState) -> AnalysisState:
    """
    Node 2: 키워드 매칭

    자소서 분석 결과를 바탕으로 pgvector에서 관련 뉴스를 검색합니다.
    여러 쿼리를 병렬로 검색하고 중복 제거 후 유사도 순으로 정렬합니다.
    """
    if state.get("error"):
        return state

    profile = state["resume_profile"]
    industry = profile["industry"]
    job_title = profile["job_title"]
    skills = profile["skills"]

    # 검색 쿼리 구성: 산업 + 직무 조합 + 상위 스킬 3개
    search_queries = [
        industry,
        f"{industry} {job_title}",
        *skills[:3],
    ]

    seen_ids: set[str] = set()
    all_results: list[dict] = []

    valid_queries = [query for query in search_queries if query.strip()]
    tasks = [
        vector_store_service.search(
            query=query,
            n_results=5,
        )
        for query in valid_queries
    ]
    results_per_query = await asyncio.gather(*tasks, return_exceptions=True)

    for query, results in zip(valid_queries, results_per_query):
        if isinstance(results, Exception):
            print(f"[Node 2] 검색 실패 (query='{query}'): {results}")
            continue

        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_results.append(r)

    # distance 오름차순 재정렬 후 최대 15건
    all_results.sort(key=lambda x: x["distance"])
    top_results = all_results[:15]

    print(f"[Node 2] 키워드 매칭 완료: {len(top_results)}건 (쿼리 {len(valid_queries)}개)")
    return {**state, "matched_news": top_results}
