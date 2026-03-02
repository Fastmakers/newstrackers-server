"""
Industry Analyzer - Analyzes industry trends from news via LangGraph.
"""

import logging

from app.agents.graphs.industry_graph import build_industry_graph
from app.schemas.data_models import IndustryData
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)


class IndustryAnalyzer:
    """Analyzes industry trends using a LangGraph pipeline."""

    def __init__(self, news_service: NewsService, llm_service: LLMService):
        self.news_service = news_service
        self.llm_service = llm_service
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = build_industry_graph(self.news_service, self.llm_service)
        return self._graph

    def analyze(self, industry: str, days_back: int = 365) -> IndustryData:
        """Run the industry analysis graph and return the result."""
        logger.info(f"Starting industry analysis for '{industry}'")

        initial_state = {
            "industry": industry,
            "days_back": days_back,
            "articles": [],
            "trends": [],
            "keywords": [],
            "monthly_sentiment": [],
            "source_stats": None,
            "result": None,
        }

        final_state = self.graph.invoke(initial_state)
        logger.info(f"Completed industry analysis for '{industry}'")
        return final_state["result"]
