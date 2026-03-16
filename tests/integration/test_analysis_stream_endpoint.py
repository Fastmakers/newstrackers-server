"""
Integration tests — POST /api/v1/analysis/stream 엔드포인트
(docs/07_progressive_stream_spec.md Phase 2)

외부 의존성:
- ReportPipeline → app.dependency_overrides 로 mock AsyncGenerator 주입
- PDF 파싱 → _extract_text_from_pdf patch
- DB → JobRepository patch
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_report_pipeline
from app.main import app
from app.services.report_pipeline import ReportInput

# ---------------------------------------------------------------------------
# 샘플 SSE 이벤트 시퀀스
# ---------------------------------------------------------------------------

_RESUME_PROFILE_DATA = {
    "company": "삼성전자",
    "job_title": "소프트웨어 개발자",
    "industry": "IT",
    "skills": ["Python", "FastAPI"],
    "experiences": ["백엔드 3년"],
}
_SWOT_DATA = {
    "strengths": ["강점1"],
    "weaknesses": ["약점1"],
    "opportunities": ["기회1"],
    "threats": ["위협1"],
}
_RESULT_DATA = {
    "resume_profile": _RESUME_PROFILE_DATA,
    "matched_news": [
        {"id": 1, "title": "기사1", "job_category": "IT", "published_at": None,
         "url": "https://example.com/1", "distance": 0.1}
    ],
    "matched_news_count": 1,
    "relevance_analysis": "### 산업 트렌드\n- 트렌드1",
    "swot": _SWOT_DATA,
    "final_report": "## 면접 준비 포인트\n내용",
}

SAMPLE_EVENTS = [
    {"type": "progress", "step": 2, "status": "start", "label": "자소서 분석 중..."},
    {"type": "progress", "step": 3, "status": "start", "label": "쿼리 최적화 중..."},
    {"type": "progress", "step": 2, "status": "done", "label": "분석 완료"},
    {"type": "progress", "step": 3, "status": "done", "label": "최적화 완료"},
    {"type": "partial", "field": "resume_profile", "data": _RESUME_PROFILE_DATA},
    {"type": "progress", "step": 4, "status": "start", "label": "뉴스 검색 중..."},
    {"type": "progress", "step": 4, "status": "done", "label": "검색 완료"},
    {"type": "partial", "field": "matched_news", "data": _RESULT_DATA["matched_news"], "count": 1},
    {"type": "progress", "step": 5, "status": "start", "label": "SWOT 분석 중..."},
    {"type": "progress", "step": 5, "status": "done", "label": "분석 완료"},
    {"type": "partial", "field": "swot", "data": _SWOT_DATA},
    {"type": "partial", "field": "relevance_analysis", "data": "### 산업 트렌드\n- 트렌드1"},
    {"type": "progress", "step": 6, "status": "start", "label": "리포트 생성 중..."},
    {"type": "token", "field": "final_report", "token": "## 면접"},
    {"type": "token", "field": "final_report", "token": " 준비 포인트\n내용"},
    {"type": "progress", "step": 6, "status": "done", "label": "완료"},
    {"type": "result", "data": _RESULT_DATA},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_fake_pdf() -> bytes:
    return b"%PDF-1.4 1 0 obj << /Type /Catalog >> endobj"


class _FakePipeline:
    """stream()이 SAMPLE_EVENTS를 순서대로 yield하는 mock 파이프라인."""

    async def stream(self, inp: ReportInput):
        for ev in SAMPLE_EVENTS:
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


@pytest.fixture
def client():
    app.dependency_overrides[get_report_pipeline] = lambda: _FakePipeline()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_report_pipeline, None)


def _post_stream(client: TestClient, extra_form: dict | None = None) -> tuple[list[dict], int]:
    """엔드포인트 호출 → (이벤트 리스트, HTTP 상태코드) 반환."""
    form = {"company": "삼성전자", "job_title": "소프트웨어 개발자",
            "industry": "IT", "career_level": "신입"}
    if extra_form:
        form.update(extra_form)

    mock_job = MagicMock()
    mock_job.id = uuid.uuid4()
    mock_report = MagicMock()
    mock_report.id = uuid.uuid4()

    with (
        patch("app.api.v1.endpoints.analysis._extract_text_from_pdf",
              return_value="자소서 내용입니다. 삼성전자 소프트웨어 개발자를 지원합니다."),
        patch("app.api.v1.endpoints.analysis.JobRepository") as MockRepo,
    ):
        repo_instance = MockRepo.return_value
        repo_instance.create_job.return_value = mock_job
        repo_instance.save_report.return_value = mock_report

        resp = client.post(
            "/api/v1/analysis/stream",
            files={"file": ("resume.pdf", _make_fake_pdf(), "application/pdf")},
            data=form,
        )

    events = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass

    return events, resp.status_code


# ---------------------------------------------------------------------------
# Test 1: 정상 흐름 — 이벤트 순서
# ---------------------------------------------------------------------------

class TestNormalFlow:
    def test_http_200(self, client):
        _, status = _post_stream(client)
        assert status == 200

    def test_all_event_types_present(self, client):
        events, _ = _post_stream(client)
        types = {e["type"] for e in events}
        assert "progress" in types
        assert "partial" in types
        assert "token" in types
        assert "result" in types

    def test_result_event_is_last(self, client):
        events, _ = _post_stream(client)
        assert events[-1]["type"] == "result"

    def test_result_event_has_job_id_and_report_id(self, client):
        events, _ = _post_stream(client)
        result = next(e for e in events if e["type"] == "result")
        assert "job_id" in result
        assert "report_id" in result
        # UUID 형식인지 확인
        uuid.UUID(result["job_id"])
        uuid.UUID(result["report_id"])

    def test_result_data_contains_report_fields(self, client):
        events, _ = _post_stream(client)
        result = next(e for e in events if e["type"] == "result")
        data = result["data"]
        assert "resume_profile" in data
        assert "matched_news" in data
        assert "swot" in data
        assert "final_report" in data

    def test_partial_events_emitted_before_result(self, client):
        events, _ = _post_stream(client)
        partial_idxs = [i for i, e in enumerate(events) if e["type"] == "partial"]
        result_idx = next(i for i, e in enumerate(events) if e["type"] == "result")
        assert len(partial_idxs) > 0
        assert all(idx < result_idx for idx in partial_idxs)

    def test_token_events_emitted(self, client):
        events, _ = _post_stream(client)
        tokens = [e for e in events if e["type"] == "token"]
        assert len(tokens) >= 1
        for t in tokens:
            assert t["field"] == "final_report"
            assert "token" in t


# ---------------------------------------------------------------------------
# Test 2: DB 저장 확인
# ---------------------------------------------------------------------------

class TestDBSave:
    def test_create_job_called_once(self, client):
        mock_job = MagicMock()
        mock_job.id = uuid.uuid4()
        mock_report = MagicMock()
        mock_report.id = uuid.uuid4()

        with (
            patch("app.api.v1.endpoints.analysis._extract_text_from_pdf",
                  return_value="자소서 내용"),
            patch("app.api.v1.endpoints.analysis.JobRepository") as MockRepo,
        ):
            repo_instance = MockRepo.return_value
            repo_instance.create_job.return_value = mock_job
            repo_instance.save_report.return_value = mock_report

            client.post(
                "/api/v1/analysis/stream",
                files={"file": ("resume.pdf", _make_fake_pdf(), "application/pdf")},
                data={"company": "삼성전자", "job_title": "개발자",
                      "industry": "IT", "career_level": "신입"},
            )

        repo_instance.create_job.assert_called_once()
        repo_instance.save_report.assert_called_once()

    def test_create_job_params_match_form(self, client):
        mock_job = MagicMock()
        mock_job.id = uuid.uuid4()
        mock_report = MagicMock()
        mock_report.id = uuid.uuid4()

        with (
            patch("app.api.v1.endpoints.analysis._extract_text_from_pdf",
                  return_value="자소서 내용"),
            patch("app.api.v1.endpoints.analysis.JobRepository") as MockRepo,
        ):
            repo_instance = MockRepo.return_value
            repo_instance.create_job.return_value = mock_job
            repo_instance.save_report.return_value = mock_report

            client.post(
                "/api/v1/analysis/stream",
                files={"file": ("resume.pdf", _make_fake_pdf(), "application/pdf")},
                data={"company": "카카오", "job_title": "프론트엔드",
                      "industry": "플랫폼", "career_level": "경력"},
            )

        call_kwargs = repo_instance.create_job.call_args.kwargs
        assert call_kwargs["company"] == "카카오"
        assert call_kwargs["job_title"] == "프론트엔드"
        assert call_kwargs["industry"] == "플랫폼"
        assert call_kwargs["career_level"] == "경력"


# ---------------------------------------------------------------------------
# Test 3: 에러 흐름 — pipeline 오류
# ---------------------------------------------------------------------------

class TestErrorFlow:
    def test_error_event_on_pipeline_failure(self, client):
        """pipeline.stream()이 예외를 throw하면 error 이벤트가 반환되어야 한다."""

        class _BrokenPipeline:
            async def stream(self, inp: ReportInput):
                yield f"data: {json.dumps({'type': 'progress', 'step': 2, 'status': 'start', 'label': '...'})}\n\n"
                raise RuntimeError("LLM 서버 오류")

        app.dependency_overrides[get_report_pipeline] = lambda: _BrokenPipeline()

        try:
            with (
                patch("app.api.v1.endpoints.analysis._extract_text_from_pdf",
                      return_value="자소서 내용"),
                patch("app.api.v1.endpoints.analysis.JobRepository") as MockRepo,
            ):
                repo_instance = MockRepo.return_value
                repo_instance.create_job.return_value = MagicMock(id=uuid.uuid4())
                repo_instance.save_report.return_value = MagicMock(id=uuid.uuid4())

                with TestClient(app) as c:
                    resp = c.post(
                        "/api/v1/analysis/stream",
                        files={"file": ("resume.pdf", _make_fake_pdf(), "application/pdf")},
                        data={"company": "삼성전자", "job_title": "개발자",
                              "industry": "IT", "career_level": "신입"},
                    )

            events = []
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data: "):
                    try:
                        events.append(json.loads(line[6:]))
                    except json.JSONDecodeError:
                        pass

            error_events = [e for e in events if e["type"] == "error"]
            assert len(error_events) >= 1
            assert "message" in error_events[0]
        finally:
            app.dependency_overrides[get_report_pipeline] = lambda: _FakePipeline()

    def test_422_when_no_file(self, client):
        resp = client.post(
            "/api/v1/analysis/stream",
            data={"company": "삼성전자"},
        )
        assert resp.status_code == 422

    def test_422_when_empty_pdf(self, client):
        with (
            patch("app.api.v1.endpoints.analysis._extract_text_from_pdf",
                  return_value=""),
        ):
            resp = client.post(
                "/api/v1/analysis/stream",
                files={"file": ("resume.pdf", _make_fake_pdf(), "application/pdf")},
                data={"company": "삼성전자"},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 4: career_level 기본값 / 파싱
# ---------------------------------------------------------------------------

class TestCareerLevelParsing:
    def test_default_career_level_is_신입(self, client):
        mock_job = MagicMock()
        mock_job.id = uuid.uuid4()
        mock_report = MagicMock()
        mock_report.id = uuid.uuid4()

        with (
            patch("app.api.v1.endpoints.analysis._extract_text_from_pdf",
                  return_value="자소서 내용"),
            patch("app.api.v1.endpoints.analysis.JobRepository") as MockRepo,
        ):
            repo_instance = MockRepo.return_value
            repo_instance.create_job.return_value = mock_job
            repo_instance.save_report.return_value = mock_report

            client.post(
                "/api/v1/analysis/stream",
                files={"file": ("resume.pdf", _make_fake_pdf(), "application/pdf")},
                data={"company": "카카오"},  # career_level 미입력
            )

        call_kwargs = repo_instance.create_job.call_args.kwargs
        assert call_kwargs["career_level"] == "신입"

    def test_invalid_career_level_defaults_to_신입(self, client):
        mock_job = MagicMock()
        mock_job.id = uuid.uuid4()
        mock_report = MagicMock()
        mock_report.id = uuid.uuid4()

        with (
            patch("app.api.v1.endpoints.analysis._extract_text_from_pdf",
                  return_value="자소서 내용"),
            patch("app.api.v1.endpoints.analysis.JobRepository") as MockRepo,
        ):
            repo_instance = MockRepo.return_value
            repo_instance.create_job.return_value = mock_job
            repo_instance.save_report.return_value = mock_report

            client.post(
                "/api/v1/analysis/stream",
                files={"file": ("resume.pdf", _make_fake_pdf(), "application/pdf")},
                data={"company": "카카오", "career_level": "invalid_value"},
            )

        call_kwargs = repo_instance.create_job.call_args.kwargs
        assert call_kwargs["career_level"] == "신입"
