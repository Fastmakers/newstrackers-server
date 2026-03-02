"""
Company Analyzer - Analyzes companies for interview preparation via LangGraph.
"""

import logging

from app.agents.graphs.company_graph import build_company_graph
from app.schemas.data_models import CompanyAnalysis
from app.services.llm_service import LLMService
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)


class CompanyAnalyzer:
    """Analyzes companies for interview preparation using a LangGraph pipeline."""

    def __init__(self, news_service: NewsService, llm_service: LLMService):
        self.news_service = news_service
        self.llm_service = llm_service
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = build_company_graph(self.news_service, self.llm_service)
        return self._graph

    def analyze(
        self,
        company: str,
        industry: str,
        resume: str,
        days_back: int = 365,
    ) -> CompanyAnalysis:
        """Run the company analysis graph and return the result."""
        logger.info(f"Starting company analysis for '{company}' in '{industry}'")

        initial_state = {
            "company": company,
            "industry": industry,
            "resume": resume,
            "days_back": days_back,
            "articles": [],
            "resume_analysis": None,
            "company_info": None,
            "radar_chart": None,
            "swot": None,
            "news_themes": [],
            "interview_qna": [],
            "risk_assessment": None,
            "result": None,
        }

        final_state = self.graph.invoke(initial_state)
        logger.info(f"Completed company analysis for '{company}'")
        return final_state["result"]
