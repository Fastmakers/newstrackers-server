"""
Unit tests — LLMService 의 Report 전용 메서드 (generate_swot_list, generate_relevance_analysis, generate_final_report)
모든 Claude API 호출은 mock 처리
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_service import LLMService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def llm():
    return LLMService(api_key="test_key")


@pytest.fixture
def sample_chunks():
    """Mock NewsChunk 리스트."""
    def make_chunk(i: int, text: str):
        chunk = MagicMock()
        chunk.chunk_text = text
        chunk.article = MagicMock()
        chunk.article.id = i
        chunk.article.title = f"기사 제목 {i}"
        return chunk

    return [
        make_chunk(1, "삼성전자 HBM3E 양산 체제 돌입. AI 서버 수요 급증으로 메모리 시장 성장."),
        make_chunk(2, "SK하이닉스, HBM4 개발 착수. 차세대 고대역폭 메모리 경쟁 가속."),
        make_chunk(3, "정부 반도체 지원책 발표. R&D 투자 세액공제 확대."),
    ]


# ---------------------------------------------------------------------------
# generate_swot_list
# ---------------------------------------------------------------------------

RESUME_TEXT = "삼성전자 소프트웨어 엔지니어 지원. Python, FastAPI 3년 경험. MSA 설계 다수."


class TestGenerateSwotList:
    def test_returns_list_per_quadrant(self, llm, sample_chunks):
        mock_resp = json.dumps({
            "strengths": ["Python/FastAPI 실전 역량이 삼성 SW직군 요구사항과 일치", "MSA 설계 경험"],
            "weaknesses": ["반도체 도메인 지식 부족"],
            "opportunities": ["삼성전자 AI SW 부문 인력 확대"],
            "threats": ["경쟁자 대비 낮은 HBM 관련 기술 경험"],
        })
        with patch.object(llm._report_generator, "_call_claude", return_value=mock_resp):
            result = llm.generate_swot_list(
                RESUME_TEXT, "삼성전자", "백엔드 개발자", sample_chunks, "반도체"
            )

        assert isinstance(result["strengths"], list)
        assert isinstance(result["weaknesses"], list)
        assert isinstance(result["opportunities"], list)
        assert isinstance(result["threats"], list)
        assert len(result["strengths"]) == 2

    def test_empty_resume_and_chunks_returns_empty(self, llm):
        result = llm.generate_swot_list("", "삼성전자", "개발자", [], "반도체")

        assert result == {
            "strengths": [],
            "weaknesses": [],
            "opportunities": [],
            "threats": [],
        }

    def test_string_value_converted_to_list(self, llm, sample_chunks):
        """LLM이 string을 반환하면 [string] 으로 변환."""
        mock_resp = json.dumps({
            "strengths": "단일 강점 문자열",
            "weaknesses": [],
            "opportunities": [],
            "threats": [],
        })
        with patch.object(llm._report_generator, "_call_claude", return_value=mock_resp):
            result = llm.generate_swot_list(RESUME_TEXT, "삼성전자", "개발자", sample_chunks)

        assert isinstance(result["strengths"], list)
        assert result["strengths"] == ["단일 강점 문자열"]

    def test_invalid_json_returns_empty(self, llm, sample_chunks):
        with patch.object(llm._report_generator, "_call_claude", return_value="not valid json"):
            result = llm.generate_swot_list(RESUME_TEXT, "삼성전자", "개발자", sample_chunks)

        assert result == {
            "strengths": [],
            "weaknesses": [],
            "opportunities": [],
            "threats": [],
        }

    def test_all_quadrants_present_even_if_partial(self, llm, sample_chunks):
        """일부 quadrant만 있어도 4개 키 모두 반환."""
        mock_resp = json.dumps({"strengths": ["강점1"]})
        with patch.object(llm._report_generator, "_call_claude", return_value=mock_resp):
            result = llm.generate_swot_list(RESUME_TEXT, "테스트", "직무", sample_chunks)

        assert set(result.keys()) == {"strengths", "weaknesses", "opportunities", "threats"}


# ---------------------------------------------------------------------------
# generate_relevance_analysis
# ---------------------------------------------------------------------------

class TestGenerateRelevanceAnalysis:
    def test_returns_markdown_string(self, llm, sample_chunks):
        mock_md = "### 산업 트렌드 요약\nHBM 시장 성장.\n\n### 역량-트렌드 연결 포인트\n메모리 기술 역량."
        with patch.object(llm._report_generator, "_call_claude", return_value=mock_md):
            result = llm.generate_relevance_analysis(
                resume="3년간 반도체 설계 업무",
                chunks=sample_chunks,
                company="삼성전자",
                industry="반도체",
                job_title="메모리 설계 엔지니어",
            )

        assert "###" in result
        assert "산업 트렌드" in result

    def test_empty_chunks_returns_empty_string(self, llm):
        result = llm.generate_relevance_analysis(
            resume="이력서 내용",
            chunks=[],
        )
        assert result == ""

    def test_calls_claude_once(self, llm, sample_chunks):
        with patch.object(llm._report_generator, "_call_claude", return_value="분석 결과") as mock_call:
            llm.generate_relevance_analysis("이력서", sample_chunks, "네이버", "AI", "개발자")

        mock_call.assert_called_once()

    def test_api_error_returns_empty_string(self, llm, sample_chunks):
        with patch.object(llm._report_generator, "_call_claude", side_effect=Exception("API timeout")):
            result = llm.generate_relevance_analysis("이력서", sample_chunks)

        assert result == ""


# ---------------------------------------------------------------------------
# generate_final_report
# ---------------------------------------------------------------------------

class TestGenerateFinalReport:
    SWOT_DATA = {
        "strengths": ["HBM 기술 리더십", "강한 R&D"],
        "weaknesses": ["높은 제조 비용"],
        "opportunities": ["AI 시장 성장"],
        "threats": ["TSMC 기술 격차"],
    }
    RELEVANCE = "### 산업 트렌드 요약\nHBM 시장 급성장 중."

    def test_returns_markdown_string(self, llm):
        mock_report = "## 면접 준비 포인트\n### Q1. HBM 관련 질문\n배경.\n**핵심 답변 방향:** 답변.\n\n## 최종 권고사항\n### 핵심 준비 사항\n1. **항목** — 내용."
        with patch.object(llm._report_generator, "_call_claude", return_value=mock_report):
            result = llm.generate_final_report(
                resume="이력서 내용",
                company="삼성전자",
                job_title="메모리 엔지니어",
                industry="반도체",
                swot=self.SWOT_DATA,
                relevance_analysis=self.RELEVANCE,
            )

        assert "면접 준비 포인트" in result
        assert "최종 권고사항" in result

    def test_api_error_returns_empty_string(self, llm):
        with patch.object(llm._report_generator, "_call_claude", side_effect=Exception("timeout")):
            result = llm.generate_final_report(
                resume="이력서",
                company="테스트",
                job_title="직무",
                industry="산업",
                swot=self.SWOT_DATA,
                relevance_analysis="",
            )

        assert result == ""

    def test_calls_claude_once(self, llm):
        with patch.object(llm._report_generator, "_call_claude", return_value="리포트") as mock_call:
            llm.generate_final_report(
                resume="이력서",
                company="네이버",
                job_title="개발자",
                industry="AI",
                swot=self.SWOT_DATA,
                relevance_analysis=self.RELEVANCE,
            )

        mock_call.assert_called_once()

    def test_empty_swot_handled_gracefully(self, llm):
        with patch.object(llm._report_generator, "_call_claude", return_value="리포트 내용"):
            result = llm.generate_final_report(
                resume="이력서",
                company="카카오",
                job_title="엔지니어",
                industry="IT",
                swot={"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
                relevance_analysis="",
            )

        assert isinstance(result, str)
