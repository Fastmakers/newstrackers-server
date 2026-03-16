"""
Unit tests — ReportPipeline.stream() partial/token event emission
Phase 1: docs/07_progressive_stream_spec.md

Coverage:
- 이벤트 타입 순서 검증 (progress / partial / token / result)
- partial 이벤트 data 구조 검증
- token 이벤트 누적 → final_report 복원 검증
- worker 하위 호환 (partial/token 무시)
"""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from app.services.report_pipeline import ReportInput, ReportPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(i: int, text: str = "뉴스 본문 샘플"):
    chunk = MagicMock()
    chunk.chunk_text = text
    chunk.distance = 0.1 * i
    article = MagicMock()
    article.id = i
    article.title = f"기사 제목 {i}"
    article.category_l2 = "IT"
    article.published_at = None
    article.article_url = f"https://example.com/news/{i}"
    chunk.article = article
    return chunk


async def _collect(pipeline: ReportPipeline, inp: ReportInput) -> list[dict]:
    """stream() 제너레이터의 모든 이벤트를 dict 리스트로 수집."""
    events: list[dict] = []
    async for raw in pipeline.stream(inp):
        line = raw.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOKENS = ["## 면접", " 준비", " 포인트\n", "내용 요약"]
FINAL_REPORT_EXPECTED = "".join(TOKENS)

SWOT_DICT = {
    "strengths": ["강점1", "강점2"],
    "weaknesses": ["약점1"],
    "opportunities": ["기회1"],
    "threats": ["위협1"],
}
RELEVANCE_ANALYSIS = "### 산업 트렌드 요약\n- 트렌드1\n- 트렌드2\n- 트렌드3"


@pytest.fixture
def pipeline():
    news = MagicMock()
    resume = MagicMock()
    report = MagicMock()

    resume.analyze_resume.return_value = {
        "skills": ["Python", "FastAPI"],
        "experience_keywords": ["백엔드 개발"],
        "target_role": "백엔드 개발자",
        "strengths": ["문제 해결력"],
        "search_keywords": ["삼성전자", "소프트웨어"],
    }
    resume.transform_query.return_value = {
        "query": "삼성전자 소프트웨어 전략 서비스",
        "keywords": ["삼성전자", "소프트웨어"],
    }
    news.hybrid_search.return_value = [_make_chunk(1), _make_chunk(2), _make_chunk(3)]
    report.generate_swot_list.return_value = SWOT_DICT
    report.generate_relevance_analysis.return_value = RELEVANCE_ANALYSIS
    report.stream_final_report.return_value = iter(TOKENS)

    return ReportPipeline(news_service=news, resume_analyzer=resume, report_generator=report)


@pytest.fixture
def inp():
    return ReportInput(
        resume_text="저는 삼성전자 소프트웨어 개발자를 지원합니다. Python, FastAPI 경험 3년.",
        company="삼성전자",
        job_title="소프트웨어 개발자",
        industry="IT/전자",
        career_level="신입",
    )


# ---------------------------------------------------------------------------
# Test 1: 이벤트 타입 순서
# ---------------------------------------------------------------------------

class TestEventOrder:
    def test_event_types_in_order(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))

        types = [e["type"] for e in events]

        # progress 이벤트가 존재해야 함
        assert "progress" in types
        # partial 이벤트가 존재해야 함
        assert "partial" in types
        # token 이벤트가 존재해야 함
        assert "token" in types
        # result 이벤트가 마지막이어야 함
        assert types[-1] == "result"

    def test_progress_steps_emitted(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))

        progress_events = [e for e in events if e["type"] == "progress"]
        steps_seen = {(e["step"], e["status"]) for e in progress_events}

        # step 2, 3, 4, 5, 6 — start/done 쌍
        for step in (2, 3, 4, 5, 6):
            assert (step, "start") in steps_seen, f"step {step} start missing"
            assert (step, "done") in steps_seen, f"step {step} done missing"

    def test_partial_before_token(self, pipeline, inp):
        """partial 이벤트는 반드시 token 이벤트보다 먼저 emit 되어야 한다."""
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))

        partial_idx = next(i for i, e in enumerate(events) if e["type"] == "partial")
        token_idx = next(i for i, e in enumerate(events) if e["type"] == "token")
        assert partial_idx < token_idx

    def test_result_is_last(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        assert events[-1]["type"] == "result"

    def test_step6_done_before_result(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))

        step6_done_idx = next(
            i for i, e in enumerate(events)
            if e["type"] == "progress" and e["step"] == 6 and e["status"] == "done"
        )
        result_idx = next(i for i, e in enumerate(events) if e["type"] == "result")
        assert step6_done_idx < result_idx


# ---------------------------------------------------------------------------
# Test 2: partial 이벤트 data 구조
# ---------------------------------------------------------------------------

class TestPartialEventStructure:
    def _partial(self, events: list[dict], field: str) -> dict:
        return next(e for e in events if e["type"] == "partial" and e["field"] == field)

    def test_resume_profile_partial_fields(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        ev = self._partial(events, "resume_profile")

        data = ev["data"]
        assert "company" in data
        assert "job_title" in data
        assert "skills" in data
        assert "experiences" in data
        assert data["company"] == "삼성전자"
        assert isinstance(data["skills"], list)

    def test_matched_news_partial_fields(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        ev = self._partial(events, "matched_news")

        assert isinstance(ev["data"], list)
        assert "count" in ev
        assert ev["count"] == len(ev["data"])
        # 개별 뉴스 아이템 구조
        item = ev["data"][0]
        assert "id" in item
        assert "title" in item
        assert "url" in item

    def test_swot_partial_fields(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        ev = self._partial(events, "swot")

        data = ev["data"]
        assert "strengths" in data
        assert "weaknesses" in data
        assert "opportunities" in data
        assert "threats" in data
        assert isinstance(data["strengths"], list)

    def test_relevance_analysis_partial_is_string(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        ev = self._partial(events, "relevance_analysis")

        assert isinstance(ev["data"], str)
        assert len(ev["data"]) > 0

    def test_matched_news_count_matches_search_results(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        ev = self._partial(events, "matched_news")

        # pipeline fixture에서 hybrid_search가 3개 반환
        assert ev["count"] == 3
        assert len(ev["data"]) == 3


# ---------------------------------------------------------------------------
# Test 3: token 이벤트 누적 → final_report 복원
# ---------------------------------------------------------------------------

class TestTokenAccumulation:
    def test_token_events_have_correct_fields(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        token_events = [e for e in events if e["type"] == "token"]

        assert len(token_events) == len(TOKENS)
        for ev in token_events:
            assert ev["field"] == "final_report"
            assert "token" in ev
            assert isinstance(ev["token"], str)

    def test_token_accumulation_restores_final_report(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        token_events = [e for e in events if e["type"] == "token"]

        reconstructed = "".join(e["token"] for e in token_events)
        assert reconstructed == FINAL_REPORT_EXPECTED

    def test_result_event_final_report_matches_tokens(self, pipeline, inp):
        """result 이벤트의 final_report가 토큰 누적 결과와 동일해야 한다."""
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))

        token_events = [e for e in events if e["type"] == "token"]
        reconstructed = "".join(e["token"] for e in token_events)

        result_event = next(e for e in events if e["type"] == "result")
        assert result_event["data"]["final_report"] == reconstructed

    def test_result_event_contains_all_fields(self, pipeline, inp):
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        result = next(e for e in events if e["type"] == "result")
        data = result["data"]

        assert "resume_profile" in data
        assert "matched_news" in data
        assert "matched_news_count" in data
        assert "swot" in data
        assert "relevance_analysis" in data
        assert "final_report" in data


# ---------------------------------------------------------------------------
# Test 4: worker 하위 호환 — partial/token 무시
# ---------------------------------------------------------------------------

# worker.py의 _STEP_PROGRESS 딕셔너리 참조
_STEP_PROGRESS = {
    (2, "start"): 15, (2, "done"): 25,
    (3, "start"): 15, (3, "done"): 25,
    (4, "start"): 30, (4, "done"): 50,
    (5, "start"): 55, (5, "done"): 75,
    (6, "start"): 80, (6, "done"): 100,
}


class TestWorkerBackwardCompat:
    def test_partial_events_not_in_step_progress(self, pipeline, inp):
        """partial 이벤트는 _STEP_PROGRESS에 키가 없어 worker에서 자동 무시된다."""
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        partial_events = [e for e in events if e["type"] == "partial"]

        assert len(partial_events) > 0, "partial 이벤트가 emit 되어야 함"
        for ev in partial_events:
            # worker의 _STEP_PROGRESS.get((step, status)) 시뮬레이션
            step = ev.get("step")
            status = ev.get("status")
            pct = _STEP_PROGRESS.get((step, status))
            assert pct is None, f"partial 이벤트 {ev}가 worker progress에 영향을 줌"

    def test_token_events_not_in_step_progress(self, pipeline, inp):
        """token 이벤트도 _STEP_PROGRESS 키가 없어 worker에서 자동 무시된다."""
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        token_events = [e for e in events if e["type"] == "token"]

        assert len(token_events) > 0, "token 이벤트가 emit 되어야 함"
        for ev in token_events:
            step = ev.get("step")
            status = ev.get("status")
            pct = _STEP_PROGRESS.get((step, status))
            assert pct is None

    def test_progress_events_all_in_step_progress(self, pipeline, inp):
        """progress 이벤트는 반드시 _STEP_PROGRESS에 매핑되어야 한다."""
        events = asyncio.get_event_loop().run_until_complete(_collect(pipeline, inp))
        progress_events = [e for e in events if e["type"] == "progress"]

        for ev in progress_events:
            step = ev["step"]
            status = ev["status"]
            pct = _STEP_PROGRESS.get((step, status))
            assert pct is not None, f"progress({step}, {status})가 _STEP_PROGRESS에 없음"


# ---------------------------------------------------------------------------
# Test 5: 에러 처리
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_error_event_on_exception(self, inp):
        """서비스 오류 시 error 이벤트가 emit 되어야 한다."""
        news = MagicMock()
        resume = MagicMock()
        report = MagicMock()

        resume.analyze_resume.side_effect = RuntimeError("API 오류")
        resume.transform_query.side_effect = RuntimeError("API 오류")

        broken = ReportPipeline(news_service=news, resume_analyzer=resume, report_generator=report)
        events = asyncio.get_event_loop().run_until_complete(_collect(broken, inp))

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "message" in error_events[0]

    def test_no_result_event_on_error(self, inp):
        """에러 발생 시 result 이벤트가 emit 되어서는 안 된다."""
        news = MagicMock()
        resume = MagicMock()
        report = MagicMock()

        resume.analyze_resume.side_effect = RuntimeError("API 오류")
        resume.transform_query.side_effect = RuntimeError("API 오류")

        broken = ReportPipeline(news_service=news, resume_analyzer=resume, report_generator=report)
        events = asyncio.get_event_loop().run_until_complete(_collect(broken, inp))

        result_events = [e for e in events if e["type"] == "result"]
        assert len(result_events) == 0
