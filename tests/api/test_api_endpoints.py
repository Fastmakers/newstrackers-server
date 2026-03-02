"""API endpoint tests."""

from datetime import datetime

from fastapi.testclient import TestClient

from app.core.dependencies import get_company_analyzer, get_industry_analyzer
from app.main import app
from app.schemas.data_models import (
    SWOT,
    CompanyAnalysis,
    CompanyInfo,
    CompanyNewsArticle,
    InterviewQNA,
    RadarChart,
    RiskAssessment,
)


class _MockIndustryAnalyzer:
    def analyze(self, industry: str, days_back: int = 365):
        return {
            "industry": industry,
            "period": {"from": "2025-01-01", "to": "2026-01-01"},
            "trends": ["트렌드1", "트렌드2", "트렌드3"],
            "keywords": [{"word": "HBM", "type": "tech", "weight": 90}],
            "monthly_sentiment": [
                {"month": "2026-01", "intensity": 5, "score": 6.5, "issue": "테스트 이슈"}
            ],
            "source_stats": {
                "total_articles": 10,
                "date_range_days": days_back,
                "top_sources": ["연합뉴스"],
                "last_updated": datetime.now().isoformat(),
            },
        }


class _MockCompanyAnalyzer:
    def analyze(self, company: str, industry: str, resume: str, days_back: int = 365):
        return CompanyAnalysis(
            company=company,
            industry=industry,
            analysis_date=datetime.now(),
            company_info=CompanyInfo(description=f"{company} 설명"),
            radar_chart=RadarChart(scores=[7.0, 6.0, 8.0, 5.0, 7.0]),
            swot=SWOT(
                strengths="강점",
                weaknesses="약점",
                opportunities="기회",
                threats="위협",
            ),
            recent_news_themes=["AI 성장", "공급망 이슈"],
            interview_qna=[
                InterviewQNA(
                    question="지원 동기는?",
                    context="기본 질문",
                    guide="구체적으로 답변",
                    difficulty="easy",
                )
            ],
            risk_assessment=RiskAssessment(
                critical_risks=["규제"],
                growth_opportunities=["시장 확대"],
                recommended_focus="기술 혁신 중심",
            ),
            news_sources=[
                CompanyNewsArticle(
                    title="테스트 기사",
                    date="2026-02-16",
                    source="연합뉴스",
                )
            ],
        )


client = TestClient(app)


def setup_module():
    app.dependency_overrides[get_industry_analyzer] = lambda: _MockIndustryAnalyzer()
    app.dependency_overrides[get_company_analyzer] = lambda: _MockCompanyAnalyzer()


def teardown_module():
    app.dependency_overrides.clear()


def test_v1_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert "timestamp" in payload


def test_industry_analysis_endpoint():
    response = client.post(
        "/api/v1/analysis/industry",
        json={"industry": "반도체", "days_back": 180},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["industry"] == "반도체"
    assert len(payload["trends"]) == 3
    assert payload["source_stats"]["date_range_days"] == 180


def test_company_analysis_endpoint():
    response = client.post(
        "/api/v1/analysis/company",
        json={
            "company": "삼성전자",
            "industry": "반도체",
            "resume": "5년차 개발자입니다.",
            "days_back": 365,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["company"] == "삼성전자"
    assert payload["radar_chart"]["scores"] == [7.0, 6.0, 8.0, 5.0, 7.0]
    assert len(payload["interview_qna"]) == 1
