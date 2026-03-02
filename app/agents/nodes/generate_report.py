import json
import time

from app.agents.state import AnalysisState
from app.services.claude_llm import claude_llm_service


async def generate_report(state: AnalysisState) -> AnalysisState:
    """
    Node 4: 리포트 생성

    자소서 분석, 뉴스 매칭, 관련성 분석 결과를 종합하여
    SWOT 분석과 최종 리포트를 생성합니다.
    """
    if state.get("error"):
        return state
    started_at = time.perf_counter()
    timings = dict(state.get("node_timings_ms") or {})

    profile = state["resume_profile"]
    relevance_analysis = state.get("relevance_analysis", "")

    skills_str = ", ".join(profile["skills"]) if profile["skills"] else "정보 없음"
    experiences_str = "\n".join(f"- {e}" for e in profile["experiences"]) or "정보 없음"

    context = (
        f"[지원자 정보]\n"
        f"- 지원 직무: {profile['job_title']}\n"
        f"- 지원 산업: {profile['industry']}\n"
        f"- 지원 회사: {profile['company'] or '미기재'}\n"
        f"- 보유 스킬: {skills_str}\n"
        f"- 주요 경험:\n{experiences_str}\n\n"
        f"[산업 동향 및 연관성 분석]\n{relevance_analysis}"
    )

    # 1차: SWOT 분석 (JSON 형식 강제)
    try:
        swot_started_at = time.perf_counter()
        swot_prompt = (
            f"{context}\n\n"
            "위 정보를 바탕으로 이 지원자의 취업 관련 SWOT 분석을 수행하세요.\n"
            "반드시 아래 JSON 형식으로만 응답하세요. 마크다운 코드 펜스나 다른 텍스트 없이 순수 JSON만 출력하세요.\n\n"
            '{"strengths": ["강점1", "강점2", "강점3"], '
            '"weaknesses": ["약점1", "약점2", "약점3"], '
            '"opportunities": ["기회1", "기회2", "기회3"], '
            '"threats": ["위협1", "위협2", "위협3"]}\n\n'
            "각 항목은 산업 동향과 지원자 프로필을 연결지어 구체적으로 작성하세요."
        )

        raw_swot = (await claude_llm_service.complete(swot_prompt, max_tokens=1500)).strip()
        if raw_swot.startswith("```"):
            lines = raw_swot.split("\n")
            raw_swot = "\n".join(lines[1:-1])
        swot = json.loads(raw_swot)
        timings["node4_swot_step"] = round((time.perf_counter() - swot_started_at) * 1000, 2)

    except Exception as e:
        print(f"[Node 4] SWOT 생성 실패: {e}")
        timings["node4_swot_step"] = round((time.perf_counter() - swot_started_at) * 1000, 2)
        swot = {
            "strengths": [],
            "weaknesses": [],
            "opportunities": [],
            "threats": [],
        }

    # 2차: 종합 리포트 (마크다운)
    try:
        report_started_at = time.perf_counter()
        swot_text = (
            f"강점: {', '.join(swot.get('strengths', []))}\n"
            f"약점: {', '.join(swot.get('weaknesses', []))}\n"
            f"기회: {', '.join(swot.get('opportunities', []))}\n"
            f"위협: {', '.join(swot.get('threats', []))}"
        )

        report_prompt = (
            f"{context}\n\n"
            f"[SWOT 분석 결과]\n{swot_text}\n\n"
            "위 모든 정보를 바탕으로 취업 지원자를 위한 종합 분석 리포트를 마크다운 형식으로 작성해주세요.\n"
            "다음 섹션을 포함하세요:\n"
            "1. 지원자 프로필 요약\n"
            "2. 현재 산업 동향 및 기회\n"
            "3. SWOT 분석\n"
            "4. 면접 준비 포인트 (산업 트렌드 기반)\n"
            "5. 최종 권고사항\n\n"
            "지원자의 강점과 산업 트렌드를 연결지어 실질적인 조언을 제공하세요."
        )
        final_report = await claude_llm_service.complete(report_prompt, max_tokens=2000)
        timings["node4_report_step"] = round((time.perf_counter() - report_started_at) * 1000, 2)
        print(
            f"[Node 4] 리포트 생성 완료 ({len(final_report)}자, "
            f"{timings['node4_report_step']}ms)"
        )

    except Exception as e:
        print(f"[Node 4] 리포트 생성 실패: {e}")
        timings["node4_report_step"] = round((time.perf_counter() - report_started_at) * 1000, 2)
        final_report = "리포트 생성 중 오류가 발생했습니다."

    timings["node4_generate_report"] = round((time.perf_counter() - started_at) * 1000, 2)
    return {**state, "swot": swot, "final_report": final_report, "node_timings_ms": timings}
