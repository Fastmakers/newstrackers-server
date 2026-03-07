"""
Test configuration and fixtures
"""

import logging
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.schemas.data_models import (
    SWOT,
    CompanyAnalysis,
    IndustryData,
    InterviewQNA,
    Keyword,
    MatchedNewsItem,
    NewsArticle,
    ReportResponse,
    ResumeProfile,
    SWOTList,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService


# ---------------------------------------------------------------------------
# 뉴스 기사 fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_articles():
    """매경 스키마 기반 샘플 뉴스 기사."""
    return [
        NewsArticle(
            id=1,
            title="HBM3E 메모리칩 공급 확대",
            body="삼성전자가 HBM3E 생산을 50% 증가시키기로 발표했습니다. 반도체 시장 성장 기대.",
            source_name="매일경제",
            published_at=datetime(2026, 2, 14),
            category_l2="경제",
        ),
        NewsArticle(
            id=2,
            title="반도체 산업 규제 강화 정책",
            body="정부가 반도체 산업 지원책을 발표했습니다. 기술 혁신 촉진 목적.",
            source_name="매일경제",
            published_at=datetime(2026, 2, 13),
            category_l2="경제",
        ),
        NewsArticle(
            id=3,
            title="AI칩셋 시장 성장 가속",
            body="AI칩셋 시장이 연 40% 성장하고 있습니다. 글로벌 수요 급증.",
            source_name="매일경제",
            published_at=datetime(2026, 2, 12),
            category_l2="IT·과학",
        ),
    ]


@pytest.fixture
def sample_keywords():
    return [
        Keyword(word="HBM3E", type="tech", weight=95),
        Keyword(word="삼성전자", type="corp", weight=90),
        Keyword(word="정부 정책", type="policy", weight=80),
        Keyword(word="AI칩", type="tech", weight=88),
    ]


# ---------------------------------------------------------------------------
# 기존 엔드포인트(/analysis/company) 관련 fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_swot():
    return SWOT(
        strengths="강점 내용",
        weaknesses="약점 내용",
        opportunities="기회 내용",
        threats="위협 내용",
    )


@pytest.fixture
def sample_interview_qna():
    return [
        InterviewQNA(
            question="회사의 도전과제에 어떻게 대처하겠습니까?",
            context="기업 전략 이해도 평가",
            guide="답변 가이드",
            difficulty="hard",
        )
    ]


@pytest.fixture
def sample_company_analysis(sample_swot, sample_interview_qna):
    return CompanyAnalysis(
        company="삼성전자",
        industry="반도체",
        analysis_date=datetime.now(),
        swot=sample_swot,
        interview_qna=sample_interview_qna,
        article_count=10,
    )


@pytest.fixture
def sample_industry_data(sample_keywords):
    return IndustryData(
        industry="반도체",
        trends=["HBM 기술 경쟁 심화", "AI칩셋 시장 급성장", "정부 지원정책 강화"],
        keywords=sample_keywords,
        article_count=100,
    )


# ---------------------------------------------------------------------------
# /report 엔드포인트 관련 fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_resume_profile():
    return ResumeProfile(
        company="삼성전자",
        job_title="백엔드 개발자",
        industry="반도체",
        skills=["Python", "FastAPI", "PostgreSQL"],
        experiences=["3년 백엔드 개발 경험", "MSA 설계 및 운영"],
    )


@pytest.fixture
def sample_swot_list():
    return SWOTList(
        strengths=["HBM 기술 리더십", "강한 R&D"],
        weaknesses=["높은 제조 비용"],
        opportunities=["AI 서버 수요 급증"],
        threats=["TSMC 기술 격차"],
    )


@pytest.fixture
def sample_matched_news():
    return [
        MatchedNewsItem(
            id=1,
            title="삼성전자 HBM3E 양산 확대",
            job_category="IT/기술",
            published_at=datetime(2026, 2, 15),
            url="https://example.com/1",
            distance=0.15,
        ),
        MatchedNewsItem(
            id=2,
            title="반도체 정책 지원 발표",
            job_category="경제",
            published_at=datetime(2026, 2, 14),
            url="https://example.com/2",
            distance=0.28,
        ),
    ]


@pytest.fixture
def sample_report_response(sample_resume_profile, sample_swot_list, sample_matched_news):
    return ReportResponse(
        resume_profile=sample_resume_profile,
        matched_news=sample_matched_news,
        matched_news_count=len(sample_matched_news),
        relevance_analysis="### 산업 트렌드 요약\nHBM 시장 성장 중.",
        swot=sample_swot_list,
        final_report="1. 면접 준비 포인트\n- HBM 언급\n\n2. 최종 권고사항\n- 차별화 강조",
    )


# ---------------------------------------------------------------------------
# 서비스 mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_news_service():
    return MagicMock(spec=NewsService)


@pytest.fixture
def mock_llm_service():
    return MagicMock(spec=LLMService)


# ---------------------------------------------------------------------------
# 로깅 설정
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
