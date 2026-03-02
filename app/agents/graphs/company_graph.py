"""
Company analysis LangGraph.

Flow (2-step parallel execution):

  Step 1 — parallel:
    fetch_articles      analyze_resume
         │                    │
         └──────────┬─────────┘
                    ↓  (both complete)

  Step 2 — parallel:
    generate_swot  score_dimensions  extract_themes  assess_risks
    extract_company_info  generate_interview_questions (uses resume_analysis)
         │
         └──────────────────────────┐
                                    ↓
                            assemble_result
                                    │
                                   END
"""

from __future__ import annotations

import logging
from datetime import datetime

from langgraph.graph import END, StateGraph

from app.agents.nodes.analysis_nodes import (
    assess_risks,
    extract_company_info,
    extract_news_themes,
    score_five_dimensions,
)
from app.agents.nodes.fetch_nodes import make_fetch_company_articles
from app.agents.nodes.llm_nodes import (
    make_analyze_resume_node,
    make_generate_interview_questions_node,
    make_generate_swot_node,
)
from app.agents.state import CompanyState
from app.schemas.data_models import (
    CompanyAnalysis,
    CompanyInfo,
    CompanyNewsArticle,
    RadarChart,
    RiskAssessment,
    SWOT,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)

# Sentinel node name shared across steps
_STEP1_SYNC = "__step1_sync__"


def _noop_sync(state: CompanyState) -> dict:
    """No-op barrier node: waits for all Step 1 nodes, then triggers Step 2."""
    return {}


def assemble_company_result(state: CompanyState) -> dict:
    """Assemble final CompanyAnalysis from accumulated state."""
    logger.info("[graph] Assembling company result")

    articles = state.get("articles", [])
    company = state["company"]

    news_sources = [
        CompanyNewsArticle(
            title=a.title,
            date=a.published_at or "",
            source=a.source or "",
        )
        for a in articles[:5]
    ]

    result = CompanyAnalysis(
        company=company,
        industry=state["industry"],
        analysis_date=datetime.now(),
        company_info=state.get("company_info") or CompanyInfo(
            description=f"{company}에 대한 정보가 제한적입니다."
        ),
        radar_chart=state.get("radar_chart") or RadarChart(scores=[5.0, 5.0, 5.0, 5.0, 5.0]),
        swot=state.get("swot") or SWOT(
            strengths="분석 실패",
            weaknesses="분석 실패",
            opportunities="분석 실패",
            threats="분석 실패",
        ),
        recent_news_themes=state.get("news_themes") or ["뉴스 분석 중"],
        interview_qna=state.get("interview_qna") or [],
        risk_assessment=state.get("risk_assessment") or RiskAssessment(
            critical_risks=["기본 시장 리스크"],
            growth_opportunities=["지속적 성장"],
            recommended_focus=f"{company}의 성장을 위한 전략이 필요합니다.",
        ),
        news_sources=news_sources,
    )
    return {"result": result}


def build_company_graph(news_service: NewsService, llm_service: LLMService):
    """Build and compile the company analysis graph.

    Two-step fan-out/fan-in:
      Step 1: fetch_articles || analyze_resume  → sync barrier
      Step 2: 6 analysis nodes in parallel      → assemble_result
    """
    graph = StateGraph(CompanyState)

    # --- Step 1 nodes ---
    graph.add_node("fetch_articles", make_fetch_company_articles(news_service))
    graph.add_node("analyze_resume", make_analyze_resume_node(llm_service))
    graph.add_node(_STEP1_SYNC, _noop_sync)

    # --- Step 2 nodes ---
    graph.add_node("generate_swot", make_generate_swot_node(llm_service))
    graph.add_node("generate_interview_questions", make_generate_interview_questions_node(llm_service))
    graph.add_node("score_dimensions", score_five_dimensions)
    graph.add_node("extract_themes", extract_news_themes)
    graph.add_node("assess_risks", assess_risks)
    graph.add_node("extract_company_info", extract_company_info)

    graph.add_node("assemble_result", assemble_company_result)

    # Entry point
    graph.set_entry_point("fetch_articles")

    # Step 1 fan-out: single entry → both parallel
    graph.add_edge("fetch_articles", "analyze_resume")

    # Step 1 fan-in: both → sync barrier
    graph.add_edge("fetch_articles", _STEP1_SYNC)
    graph.add_edge("analyze_resume", _STEP1_SYNC)

    # Step 2 fan-out: barrier → 6 parallel nodes
    graph.add_edge(_STEP1_SYNC, "generate_swot")
    graph.add_edge(_STEP1_SYNC, "generate_interview_questions")
    graph.add_edge(_STEP1_SYNC, "score_dimensions")
    graph.add_edge(_STEP1_SYNC, "extract_themes")
    graph.add_edge(_STEP1_SYNC, "assess_risks")
    graph.add_edge(_STEP1_SYNC, "extract_company_info")

    # Step 2 fan-in: all 6 → assemble
    graph.add_edge("generate_swot", "assemble_result")
    graph.add_edge("generate_interview_questions", "assemble_result")
    graph.add_edge("score_dimensions", "assemble_result")
    graph.add_edge("extract_themes", "assemble_result")
    graph.add_edge("assess_risks", "assemble_result")
    graph.add_edge("extract_company_info", "assemble_result")

    graph.add_edge("assemble_result", END)

    return graph.compile()
