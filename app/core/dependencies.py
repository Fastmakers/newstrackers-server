"""FastAPI dependency providers."""

from functools import lru_cache

from app.services.llm_service import LLMService
from app.services.news_service import NewsService


@lru_cache
def get_news_service() -> NewsService:
    return NewsService()


@lru_cache
def get_llm_service() -> LLMService:
    return LLMService()
