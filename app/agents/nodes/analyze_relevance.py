import time

from app.agents.state import AnalysisState
from app.services.claude_llm import claude_llm_service


async def analyze_relevance(state: AnalysisState) -> AnalysisState:
    """
    Node 3: 관련성 분석

    매칭된 뉴스와 지원자 프로필을 바탕으로 산업 동향과
    지원자와의 연관성을 Claude로 분석합니다.
    """
    if state.get("error"):
        return state
    started_at = time.perf_counter()
    timings = dict(state.get("node_timings_ms") or {})

    profile = state["resume_profile"]
    matched_news = state.get("matched_news") or []

    if not matched_news:
        timings["node3_analyze_relevance"] = round((time.perf_counter() - started_at) * 1000, 2)
        return {
            **state,
            "relevance_analysis": "관련 뉴스 데이터가 없어 분석을 진행할 수 없습니다.",
            "node_timings_ms": timings,
        }

    news_texts = "\n---\n".join(
        n["document"] for n in matched_news if n.get("document")
    )

    skills_str = ", ".join(profile["skills"]) if profile["skills"] else "정보 없음"
    experiences_str = "\n".join(f"- {e}" for e in profile["experiences"]) or "정보 없음"

    try:
        prompt = (
            f"다음은 '{profile['industry']}' 산업 관련 최신 뉴스 모음입니다.\n\n"
            f"[뉴스 데이터]\n{news_texts}\n\n"
            f"---\n"
            f"[지원자 정보]\n"
            f"- 지원 직무: {profile['job_title']}\n"
            f"- 지원 회사: {profile['company'] or '미기재'}\n"
            f"- 보유 스킬: {skills_str}\n"
            f"- 주요 경험:\n{experiences_str}\n\n"
            "다음 두 가지를 한국어로 분석해주세요:\n"
            "1. 현재 산업의 주요 트렌드와 핵심 이슈 (3~5개)\n"
            "2. 이 트렌드가 지원자의 스킬/경험과 어떻게 연관되는지 구체적으로 분석"
        )
        analysis = await claude_llm_service.complete(prompt, max_tokens=1500)
        timings["node3_analyze_relevance"] = round((time.perf_counter() - started_at) * 1000, 2)
        print(f"[Node 3] 관련성 분석 완료 ({len(analysis)}자, {timings['node3_analyze_relevance']}ms)")
        return {**state, "relevance_analysis": analysis, "node_timings_ms": timings}

    except Exception as e:
        print(f"[Node 3] 관련성 분석 실패: {e}")
        timings["node3_analyze_relevance"] = round((time.perf_counter() - started_at) * 1000, 2)
        return {**state, "error": f"관련성 분석 실패: {e}", "node_timings_ms": timings}
