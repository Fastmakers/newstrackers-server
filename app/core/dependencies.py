"""FastAPI dependency providers — 명시적 DI 체인.

의존성 그래프:
    EmbeddingService
        └── NewsService
    LLMClient
        ├── ResumeAnalyzer
        ├── ReportGenerator
        └── LLMService  (backward-compat facade)
    ReportPipeline(NewsService, ResumeAnalyzer, ReportGenerator)
"""

from functools import lru_cache

from app.services.embedding_service import EmbeddingService
from app.services.llm_client import LLMClient
from app.services.llm_service import LLMService
from app.services.news_service import NewsService
from app.services.report_generator import ReportGenerator
from app.services.report_pipeline import ReportPipeline
from app.services.resume_analyzer import ResumeAnalyzer


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


@lru_cache
def get_resume_analyzer() -> ResumeAnalyzer:
    return ResumeAnalyzer()


@lru_cache
def get_report_generator() -> ReportGenerator:
    return ReportGenerator()


@lru_cache
def get_news_service() -> NewsService:
    return NewsService(embedding_service=get_embedding_service())


@lru_cache
def get_llm_service() -> LLMService:
    return LLMService()


@lru_cache
def get_report_pipeline() -> ReportPipeline:
    return ReportPipeline(
        news_service=get_news_service(),
        resume_analyzer=get_resume_analyzer(),
        report_generator=get_report_generator(),
    )
