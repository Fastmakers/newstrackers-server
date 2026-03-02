"""
Test configuration and fixtures
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.analysis.company_analyzer import CompanyAnalyzer
from app.analysis.industry_analyzer import IndustryAnalyzer
from app.schemas.data_models import (
    SWOT,
    CompanyAnalysis,
    IndustryData,
    InterviewQNA,
    Keyword,
    MonthlySentiment,
    NewsArticle,
    RadarChart,
)
from app.services.llm_service import LLMService
from app.services.news_service import NewsService


@pytest.fixture
def sample_articles():
    """Fixture: Sample news articles (매경 2025 schema)"""
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
    """Fixture: Sample keywords"""
    return [
        Keyword(word="HBM3E", type="tech", weight=95),
        Keyword(word="삼성전자", type="corp", weight=90),
        Keyword(word="정부 정책", type="policy", weight=80),
        Keyword(word="AI칩", type="tech", weight=88),
    ]


@pytest.fixture
def sample_monthly_sentiment():
    """Fixture: Sample monthly sentiment data"""
    sentiments = []
    base_date = datetime.now()
    for i in range(12):
        month = (base_date - timedelta(days=30 * i)).strftime("%Y-%m")
        sentiments.insert(0, MonthlySentiment(
            month=month,
            intensity=5 + (i % 5),
            score=float(6 + (i % 4)),
            issue=f"Issue {i}",
        ))
    return sentiments


@pytest.fixture
def sample_industry_data(sample_keywords, sample_monthly_sentiment):
    """Fixture: Sample industry analysis data"""
    return IndustryData(
        industry="반도체",
        period={"from": "2025-02-16", "to": "2026-02-16"},
        trends=[
            "HBM 기술 경쟁 심화",
            "AI칩셋 시장 급성장",
            "정부 지원정책 강화",
        ],
        keywords=sample_keywords,
        monthly_sentiment=sample_monthly_sentiment,
    )


@pytest.fixture
def sample_radar_chart():
    """Fixture: Sample radar chart data"""
    return RadarChart(scores=[8, 7, 9, 6, 8])


@pytest.fixture
def sample_swot():
    """Fixture: Sample SWOT analysis"""
    return SWOT(
        strengths="강점 내용",
        weaknesses="약점 내용",
        opportunities="기회 내용",
        threats="위협 내용",
    )


@pytest.fixture
def sample_interview_qna():
    """Fixture: Sample interview Q&A"""
    return [
        InterviewQNA(
            question="회사의 도전과제에 어떻게 대처하겠습니까?",
            context="기업 전략 이해도 평가",
            guide="답변 가이드",
            difficulty="hard",
        )
    ]


@pytest.fixture
def sample_company_analysis(sample_radar_chart, sample_swot, sample_interview_qna):
    """Fixture: Sample company analysis"""
    return CompanyAnalysis(
        company="삼성전자",
        industry="반도체",
        analysis_date=datetime.now(),
        radar_chart=sample_radar_chart,
        swot=sample_swot,
        recent_news_themes=["HBM3E 생산", "AI칩 개발"],
        interview_qna=sample_interview_qna,
        risk_assessment={
            "critical_risks": ["기술 경쟁", "시장 변화"],
            "growth_opportunities": ["AI 시장", "신기술"],
            "recommended_focus": "기술 혁신 중심",
        },
    )


# --- DI-based mock fixtures ---

@pytest.fixture
def mock_news_service():
    """Mock NewsService for testing."""
    return MagicMock(spec=NewsService)


@pytest.fixture
def mock_llm_service():
    """Mock LLMService for testing."""
    return MagicMock(spec=LLMService)


@pytest.fixture
def industry_analyzer(mock_news_service, mock_llm_service):
    """IndustryAnalyzer with mocked dependencies."""
    return IndustryAnalyzer(
        news_service=mock_news_service,
        llm_service=mock_llm_service,
    )


@pytest.fixture
def company_analyzer(mock_news_service, mock_llm_service):
    """CompanyAnalyzer with mocked dependencies."""
    return CompanyAnalyzer(
        news_service=mock_news_service,
        llm_service=mock_llm_service,
    )


# Logging configuration
@pytest.fixture(scope="session", autouse=True)
def setup_logging():
    """Setup logging for tests"""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
