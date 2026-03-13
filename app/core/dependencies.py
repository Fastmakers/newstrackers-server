"""FastAPI dependency providers — 명시적 DI 체인.

의존성 그래프:
    EmbeddingService
        └── NewsService
    LLMClient
        ├── ResumeAnalyzer
        ├── ReportGenerator
        └── LLMService  (backward-compat facade)
    ReportPipeline(NewsService, ResumeAnalyzer, ReportGenerator)
    AnalysisWorker  (싱글톤, lifespan에서 start/stop)
    get_current_user  (JWT 필수 인증 의존성)
"""

from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_access_token
from app.db.base import get_db
from app.db.user_models import UserDB
from app.services.report_pipeline import ReportPipeline
from app.services.worker import AnalysisWorker

security = HTTPBearer()


@lru_cache
def get_embedding_service() -> Any:
    from app.services.embedding_service import EmbeddingService
    return EmbeddingService()


@lru_cache
def get_llm_client() -> Any:
    from app.services.llm_client import LLMClient
    return LLMClient()


@lru_cache
def get_resume_analyzer() -> Any:
    if settings.EXPERIMENT_USE_FAKE_PIPELINE:
        from app.services.fake_pipeline import FakeResumeAnalyzer
        return FakeResumeAnalyzer()
    from app.services.resume_analyzer import ResumeAnalyzer
    return ResumeAnalyzer()


@lru_cache
def get_report_generator() -> Any:
    if settings.EXPERIMENT_USE_FAKE_PIPELINE:
        from app.services.fake_pipeline import FakeReportGenerator
        return FakeReportGenerator()
    from app.services.report_generator import ReportGenerator
    return ReportGenerator()


@lru_cache
def get_news_service() -> Any:
    if settings.EXPERIMENT_USE_FAKE_PIPELINE:
        from app.services.fake_pipeline import FakeNewsService
        return FakeNewsService()
    from app.services.news_service import NewsService
    return NewsService(embedding_service=get_embedding_service())


@lru_cache
def get_llm_service() -> Any:
    from app.services.llm_service import LLMService
    return LLMService()


@lru_cache
def get_report_pipeline() -> ReportPipeline:
    return ReportPipeline(
        news_service=get_news_service(),
        resume_analyzer=get_resume_analyzer(),
        report_generator=get_report_generator(),
    )


@lru_cache
def get_worker() -> AnalysisWorker:
    worker = AnalysisWorker(
        poll_interval_sec=settings.WORKER_POLL_INTERVAL_SEC,
        max_concurrent=settings.WORKER_MAX_CONCURRENT,
    )
    worker.set_pipeline(get_report_pipeline())
    return worker


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> UserDB:
    """Authorization 헤더에서 JWT를 검증하고 현재 사용자를 반환한다.

    토큰이 유효하지 않거나 만료된 경우 401을 반환한다.
    선택적 인증이 필요하면 app.core.auth.get_optional_user_id 를 사용할 것.
    """
    user_id = verify_access_token(credentials.credentials)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰입니다.",
        )

    user = db.query(UserDB).filter(UserDB.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유저를 찾을 수 없습니다.",
        )

    return user
