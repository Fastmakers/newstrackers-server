"""FastAPI dependency providers."""

from functools import lru_cache

from app.analysis.company_analyzer import CompanyAnalyzer
from app.analysis.industry_analyzer import IndustryAnalyzer
from app.services.llm_service import LLMService
from app.services.news_service import NewsService


@lru_cache
def get_news_service() -> NewsService:
    return NewsService()


@lru_cache
def get_llm_service() -> LLMService:
    return LLMService()


@lru_cache
def get_industry_analyzer() -> IndustryAnalyzer:
    return IndustryAnalyzer(
        news_service=get_news_service(),
        llm_service=get_llm_service(),
    )


@lru_cache
def get_company_analyzer() -> CompanyAnalyzer:
    return CompanyAnalyzer(
        news_service=get_news_service(),
        llm_service=get_llm_service(),
    )
