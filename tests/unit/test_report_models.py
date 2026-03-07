"""
Unit tests — ReportResponse 관련 Pydantic 모델 검증
"""

import pytest
from datetime import datetime

from app.schemas.data_models import (
    MatchedNewsItem,
    ReportResponse,
    ResumeProfile,
    SWOTList,
)


class TestResumeProfile:
    def test_defaults(self):
        profile = ResumeProfile()
        assert profile.company == ""
        assert profile.job_title == ""
        assert profile.industry == ""
        assert profile.skills == []
        assert profile.experiences == []

    def test_full_data(self):
        profile = ResumeProfile(
            company="삼성전자",
            job_title="백엔드 개발자",
            industry="반도체",
            skills=["Python", "FastAPI"],
            experiences=["3년 개발 경험", "MSA 설계"],
        )
        assert profile.company == "삼성전자"
        assert len(profile.skills) == 2
        assert len(profile.experiences) == 2


class TestMatchedNewsItem:
    def test_defaults(self):
        item = MatchedNewsItem(id=1, title="테스트 기사")
        assert item.id == 1
        assert item.title == "테스트 기사"
        assert item.job_category == ""
        assert item.url == ""
        assert item.distance == 0.0
        assert item.published_at is None

    def test_with_all_fields(self):
        item = MatchedNewsItem(
            id=42,
            title="삼성전자 HBM3E 양산",
            job_category="IT/기술",
            published_at=datetime(2026, 2, 15, 9, 0, 0),
            url="https://example.com/news/1",
            distance=0.18,
        )
        assert item.id == 42
        assert item.distance == 0.18
        assert item.published_at.year == 2026

    def test_distance_range(self):
        item = MatchedNewsItem(id=1, title="기사", distance=0.99)
        assert 0.0 <= item.distance <= 1.0


class TestSWOTList:
    def test_defaults(self):
        swot = SWOTList()
        assert swot.strengths == []
        assert swot.weaknesses == []
        assert swot.opportunities == []
        assert swot.threats == []

    def test_with_data(self):
        swot = SWOTList(
            strengths=["강점1", "강점2"],
            weaknesses=["약점1"],
            opportunities=["기회1", "기회2"],
            threats=["위협1"],
        )
        assert len(swot.strengths) == 2
        assert len(swot.weaknesses) == 1
        assert swot.strengths[0] == "강점1"

    def test_all_items_are_strings(self):
        swot = SWOTList(
            strengths=["a", "b"],
            weaknesses=["c"],
            opportunities=["d"],
            threats=["e", "f"],
        )
        for quadrant in [swot.strengths, swot.weaknesses, swot.opportunities, swot.threats]:
            for item in quadrant:
                assert isinstance(item, str)


class TestReportResponse:
    def test_minimal(self):
        response = ReportResponse(
            resume_profile=ResumeProfile(),
            swot=SWOTList(),
        )
        assert response.matched_news == []
        assert response.matched_news_count == 0
        assert response.relevance_analysis == ""
        assert response.final_report == ""

    def test_full_response(self):
        profile = ResumeProfile(
            company="네이버",
            job_title="데이터 엔지니어",
            industry="AI 인공지능",
            skills=["Python", "Spark"],
            experiences=["데이터 파이프라인 구축"],
        )
        news = [
            MatchedNewsItem(
                id=1,
                title="네이버 AI 플랫폼 확장",
                job_category="IT",
                published_at=datetime(2026, 1, 10),
                url="https://example.com/1",
                distance=0.12,
            ),
            MatchedNewsItem(
                id=2,
                title="AI 검색 기술 고도화",
                job_category="IT",
                published_at=datetime(2026, 1, 8),
                url="https://example.com/2",
                distance=0.25,
            ),
        ]
        swot = SWOTList(
            strengths=["검색 기술 리더십"],
            weaknesses=["해외 진출 한계"],
            opportunities=["AI 시장 급성장"],
            threats=["글로벌 빅테크 경쟁"],
        )

        response = ReportResponse(
            resume_profile=profile,
            matched_news=news,
            matched_news_count=len(news),
            relevance_analysis="### 산업 트렌드\nAI 플랫폼 성장",
            swot=swot,
            final_report="## 면접 준비 포인트\n- 데이터 파이프라인 경험 강조",
        )

        assert response.resume_profile.company == "네이버"
        assert len(response.matched_news) == 2
        assert response.matched_news_count == 2
        assert "산업 트렌드" in response.relevance_analysis
        assert len(response.swot.strengths) == 1
        assert "면접 준비 포인트" in response.final_report

    def test_json_serialization(self):
        """JSON 직렬화 — 프론트엔드 수신 포맷 확인."""
        response = ReportResponse(
            resume_profile=ResumeProfile(company="카카오", skills=["Java"]),
            matched_news=[
                MatchedNewsItem(id=1, title="카카오 AI 투자", distance=0.2)
            ],
            matched_news_count=1,
            swot=SWOTList(strengths=["플랫폼 지배력"]),
        )
        data = response.model_dump()

        assert "resume_profile" in data
        assert "matched_news" in data
        assert "swot" in data
        assert isinstance(data["swot"]["strengths"], list)
        assert isinstance(data["matched_news"][0]["distance"], float)
