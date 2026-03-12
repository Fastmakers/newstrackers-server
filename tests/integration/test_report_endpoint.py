"""
Integration tests — POST /api/v1/analysis/report 엔드포인트
모든 외부 의존성(ReportPipeline 내부 서비스)은 mock 처리
"""

import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_report_pipeline
from app.schemas.data_models import NewsChunk, NewsArticle
from app.services.report_pipeline import ReportPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_chunk(article_id: int, title: str, distance: float = 0.2):
    chunk = MagicMock(spec=NewsChunk)
    chunk.chunk_text = f"뉴스 내용 {article_id}"
    chunk.distance = distance
    article = MagicMock(spec=NewsArticle)
    article.id = article_id
    article.title = title
    article.category_l2 = "IT/기술"
    article.published_at = datetime(2026, 2, 15)
    article.article_url = f"https://example.com/news/{article_id}"
    chunk.article = article
    return chunk


def make_pdf_bytes(text: str = "자소서 내용입니다.") -> bytes:
    """pypdf가 파싱할 수 있는 최소 PDF 바이트 생성."""
    return b"%PDF-1.4 fake content " + text.encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_resume_analyzer():
    svc = MagicMock()
    svc.analyze_resume.return_value = {
        "skills": ["Python", "FastAPI"],
        "experience_keywords": ["3년 백엔드 개발", "MSA 설계"],
        "target_role": "백엔드 개발자",
        "strengths": ["문제 해결력", "협업 능력"],
        "search_keywords": ["삼성전자", "반도체", "소프트웨어"],
    }
    svc.transform_query.return_value = {
        "keywords": ["삼성전자", "소프트웨어"],
        "query": "삼성전자 소프트웨어 개발 AI 전략",
    }
    return svc


@pytest.fixture
def mock_report_generator():
    svc = MagicMock()
    svc.generate_swot_list.return_value = {
        "strengths": ["HBM 기술 리더십", "강한 R&D"],
        "weaknesses": ["높은 제조 비용"],
        "opportunities": ["AI 서버 수요"],
        "threats": ["TSMC 기술 격차"],
    }
    svc.generate_relevance_analysis.return_value = (
        "### 산업 트렌드 요약\nHBM 시장 성장.\n\n### 역량-트렌드 연결 포인트\n개발 역량 연결."
    )
    svc.generate_final_report.return_value = (
        "## 면접 준비 포인트\n- HBM 기술 언급\n\n## 최종 권고사항\n- 기술 차별화 강조"
    )
    return svc


@pytest.fixture
def mock_news():
    svc = MagicMock()
    svc.hybrid_search.return_value = [
        make_mock_chunk(1, "삼성전자 HBM3E 양산 확대", 0.15),
        make_mock_chunk(2, "반도체 정책 지원 발표", 0.28),
        make_mock_chunk(3, "AI 서버 수요 급증", 0.32),
    ]
    return svc


@pytest.fixture
def client(mock_resume_analyzer, mock_report_generator, mock_news):
    pipeline = ReportPipeline(
        news_service=mock_news,
        resume_analyzer=mock_resume_analyzer,
        report_generator=mock_report_generator,
    )
    app.dependency_overrides[get_report_pipeline] = lambda: pipeline
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests — 정상 케이스
# ---------------------------------------------------------------------------

class TestReportEndpointSuccess:
    PDF_TEXT = "삼성전자 소프트웨어 개발자 지원 자기소개서. Python, FastAPI 역량 보유."

    def _post_report(self, client, **extra_fields):
        pdf_bytes = make_pdf_bytes(self.PDF_TEXT)
        files = {"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        data = {
            "industry": "반도체",
            "company": "삼성전자",
            "job_title": "백엔드 개발자",
            "include_raw_news": "true",
            "report_mode": "fast",
            **extra_fields,
        }
        with patch("app.api.v1.endpoints.resume._extract_text_from_pdf",
                   return_value=self.PDF_TEXT):
            return client.post("/api/v1/analysis/report", files=files, data=data)

    def test_status_200(self, client):
        resp = self._post_report(client)
        assert resp.status_code == 200

    def test_response_has_all_required_fields(self, client):
        resp = self._post_report(client)
        body = resp.json()

        assert "resume_profile" in body
        assert "matched_news" in body
        assert "matched_news_count" in body
        assert "relevance_analysis" in body
        assert "swot" in body
        assert "final_report" in body

    def test_resume_profile_fields(self, client):
        resp = self._post_report(client)
        profile = resp.json()["resume_profile"]

        assert profile["company"] == "삼성전자"
        assert profile["job_title"] == "백엔드 개발자"
        assert profile["industry"] == "반도체"
        assert isinstance(profile["skills"], list)
        assert isinstance(profile["experiences"], list)

    def test_matched_news_structure(self, client):
        resp = self._post_report(client)
        news = resp.json()["matched_news"]

        assert isinstance(news, list)
        assert len(news) == 3
        first = news[0]
        assert "id" in first
        assert "title" in first
        assert "job_category" in first
        assert "published_at" in first
        assert "url" in first
        assert "distance" in first

    def test_matched_news_count_equals_list_length(self, client):
        resp = self._post_report(client)
        body = resp.json()

        assert body["matched_news_count"] == len(body["matched_news"])

    def test_swot_contains_lists(self, client):
        resp = self._post_report(client)
        swot = resp.json()["swot"]

        for key in ["strengths", "weaknesses", "opportunities", "threats"]:
            assert key in swot
            assert isinstance(swot[key], list)

    def test_relevance_analysis_is_string(self, client):
        resp = self._post_report(client)
        assert isinstance(resp.json()["relevance_analysis"], str)

    def test_final_report_contains_expected_sections(self, client):
        resp = self._post_report(client)
        final = resp.json()["final_report"]

        assert "면접 준비 포인트" in final
        assert "최종 권고사항" in final

    def test_form_params_override_resume_profile(self, client):
        """Form의 company/job_title이 자소서 분석 결과보다 우선."""
        resp = self._post_report(client, company="네이버", job_title="데이터 엔지니어")
        profile = resp.json()["resume_profile"]

        assert profile["company"] == "네이버"
        assert profile["job_title"] == "데이터 엔지니어"

    def test_without_optional_params(self, client):
        """company, industry, job_title 없이 PDF만으로 요청."""
        pdf_bytes = make_pdf_bytes(self.PDF_TEXT)
        files = {"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        with patch("app.api.v1.endpoints.resume._extract_text_from_pdf",
                   return_value=self.PDF_TEXT):
            resp = client.post("/api/v1/analysis/report", files=files)

        assert resp.status_code == 200
        body = resp.json()
        assert "resume_profile" in body

    def test_hybrid_search_called_with_query(self, client, mock_news):
        self._post_report(client)
        mock_news.hybrid_search.assert_called_once()

    def test_llm_pipeline_called_in_order(self, client, mock_resume_analyzer, mock_report_generator):
        self._post_report(client)
        mock_resume_analyzer.analyze_resume.assert_called_once()
        mock_resume_analyzer.transform_query.assert_called_once()
        mock_report_generator.generate_swot_list.assert_called_once()
        mock_report_generator.generate_relevance_analysis.assert_called_once()
        mock_report_generator.generate_final_report.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — 에러 케이스
# ---------------------------------------------------------------------------

class TestReportEndpointErrors:
    def test_missing_file_returns_422(self, client):
        resp = client.post(
            "/api/v1/analysis/report",
            data={"industry": "반도체"},
        )
        assert resp.status_code == 422

    def test_non_pdf_file_returns_415(self, client):
        files = {"file": ("resume.txt", io.BytesIO(b"text content"), "text/plain")}
        with patch("app.api.v1.endpoints.resume._extract_text_from_pdf",
                   return_value="내용"):
            resp = client.post(
                "/api/v1/analysis/report",
                files=files,
                data={"company": "삼성전자"},
            )
        assert resp.status_code == 415

    def test_empty_pdf_returns_422(self, client):
        files = {"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
        with patch("app.api.v1.endpoints.resume._extract_text_from_pdf",
                   return_value="   "):
            resp = client.post(
                "/api/v1/analysis/report",
                files=files,
                data={"company": "삼성전자"},
            )
        assert resp.status_code == 422

    def test_oversized_file_returns_413(self, client):
        big_bytes = b"a" * (6 * 1024 * 1024)  # 6MB
        files = {"file": ("big.pdf", io.BytesIO(big_bytes), "application/pdf")}
        resp = client.post(
            "/api/v1/analysis/report",
            files=files,
            data={"company": "삼성전자"},
        )
        assert resp.status_code == 413

    def test_no_news_results_still_returns_200(self, client, mock_news):
        """검색 결과 0건이어도 200 반환."""
        mock_news.hybrid_search.return_value = []
        pdf_bytes = make_pdf_bytes("자소서 내용")
        files = {"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        with patch("app.api.v1.endpoints.resume._extract_text_from_pdf",
                   return_value="자소서 내용"):
            resp = client.post(
                "/api/v1/analysis/report",
                files=files,
                data={"company": "삼성전자"},
            )
        assert resp.status_code == 200
        assert resp.json()["matched_news_count"] == 0
        assert resp.json()["matched_news"] == []
