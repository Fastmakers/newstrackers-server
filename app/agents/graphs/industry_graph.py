"""
Industry analysis LangGraph.

Flow:
    fetch_articles
         |
    ┌────┼────┬──────────────┐
    ↓    ↓    ↓              ↓
 trends  keywords  sentiment  source_stats   ← parallel
    └────┴────┴──────────────┘
         |
    assemble_result
         |
        END
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from langgraph.graph import END, StateGraph

from app.agents.nodes.analysis_nodes import compute_monthly_sentiment, compute_source_stats
from app.agents.nodes.fetch_nodes import make_fetch_industry_articles
from app.agents.nodes.llm_nodes import make_extract_keywords_node, make_extract_trends_node
from app.agents.state import IndustryState
from app.schemas.data_models import IndustryData, SourceStats
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)


def make_assemble_industry_result(days_back: int = 365):
    """Node factory: assemble final IndustryData from accumulated state."""

    def assemble_result(state: IndustryState) -> dict:
        logger.info("[graph] Assembling industry result")
        days = state.get("days_back", days_back)
        articles = state.get("articles", [])

        source_stats = state.get("source_stats") or SourceStats(
            total_articles=len(articles),
            date_range_days=days,
            top_sources=[],
            last_updated=datetime.now(),
        )

        trends = state.get("trends")
        if not isinstance(trends, list) or len(trends) < 3:
            trends = [
                "뉴스 데이터를 찾을 수 없습니다.",
                "DB에 데이터를 로드해주세요.",
                "다시 시도해주세요.",
            ]

        keywords = state.get("keywords")
        if not isinstance(keywords, list):
            keywords = []

        monthly_sentiment = state.get("monthly_sentiment")
        if not isinstance(monthly_sentiment, list):
            monthly_sentiment = []

        result = IndustryData(
            industry=state["industry"],
            period={
                "from": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
                "to": datetime.now().strftime("%Y-%m-%d"),
            },
            trends=trends,
            keywords=keywords,
            monthly_sentiment=monthly_sentiment,
            source_stats=source_stats,
        )
        return {"result": result}

    return assemble_result


def build_industry_graph(news_service: NewsService, llm_service: LLMService):
    """Build and compile the industry analysis graph."""
    graph = StateGraph(IndustryState)

    # Register nodes
    graph.add_node("fetch_articles", make_fetch_industry_articles(news_service))
    graph.add_node("extract_trends", make_extract_trends_node(llm_service))
    graph.add_node("extract_keywords", make_extract_keywords_node(llm_service))
    graph.add_node("compute_sentiment", compute_monthly_sentiment)
    graph.add_node("compute_source_stats", compute_source_stats)
    graph.add_node("assemble_result", make_assemble_industry_result())

    # Entry point
    graph.set_entry_point("fetch_articles")

    # Fan-out: fetch → 4 parallel nodes
    graph.add_edge("fetch_articles", "extract_trends")
    graph.add_edge("fetch_articles", "extract_keywords")
    graph.add_edge("fetch_articles", "compute_sentiment")
    graph.add_edge("fetch_articles", "compute_source_stats")

    # Fan-in: all 4 → assemble (LangGraph waits for all to complete)
    graph.add_edge("extract_trends", "assemble_result")
    graph.add_edge("extract_keywords", "assemble_result")
    graph.add_edge("compute_sentiment", "assemble_result")
    graph.add_edge("compute_source_stats", "assemble_result")

    graph.add_edge("assemble_result", END)

    return graph.compile()
