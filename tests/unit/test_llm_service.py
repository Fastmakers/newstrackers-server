"""
Unit tests for LLM service
"""

import json
from unittest.mock import patch

import pytest

from app.services.llm_service import LLMService


class TestLLMService:
    """Test LLM service functionality"""

    def test_llm_service_initialization(self):
        """Test LLM service can be initialized"""
        service = LLMService(api_key="test_key")

        assert service.api_key == "test_key"
        assert service.model == "claude-sonnet-4-6"
        assert service.max_tokens == 2000

    def test_fail_fast_on_empty_api_key(self):
        """Test that empty API key raises ValueError when no env fallback exists"""
        with patch("app.services.llm_service.settings") as mock_settings:
            mock_settings.ANTHROPIC_API_KEY = ""
            mock_settings.LLM_MODEL = "claude-sonnet-4-6"
            mock_settings.MAX_TOKENS = 2000
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is required"):
                LLMService(api_key="")

    def test_extract_trends_empty_articles(self):
        """Test trend extraction with empty articles"""
        service = LLMService(api_key="test_key")

        result = service.extract_trends([], "반도체")

        assert len(result) == 3
        assert "데이터 부족" in result[0]


class TestExtractJson:
    """Test the _extract_json helper"""

    def test_plain_json(self):
        """Test parsing plain JSON"""
        result = LLMService._extract_json('[{"key": "value"}]')
        assert result == [{"key": "value"}]

    def test_markdown_fenced_json(self):
        """Test parsing JSON wrapped in ```json fences"""
        result = LLMService._extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_generic_fenced_json(self):
        """Test parsing JSON wrapped in ``` fences"""
        result = LLMService._extract_json('```\n[1, 2, 3]\n```')
        assert result == [1, 2, 3]

    def test_invalid_json_raises(self):
        """Test that invalid JSON raises JSONDecodeError"""
        with pytest.raises(json.JSONDecodeError):
            LLMService._extract_json("not valid json")

    def test_whitespace_handling(self):
        """Test that leading/trailing whitespace is handled"""
        result = LLMService._extract_json('  \n {"a": 1} \n  ')
        assert result == {"a": 1}


class TestLLMServiceMocked:
    """Test LLM methods with mocked Claude API"""

    def test_extract_keywords_success(self, sample_articles):
        """Test keyword extraction with mocked response"""
        service = LLMService(api_key="test_key")
        mock_response = '[{"word": "HBM3E", "type": "tech", "weight": 95}]'

        with patch.object(service, "_call_claude", return_value=mock_response):
            result = service.extract_keywords(sample_articles, top_n=5)

        assert len(result) == 1
        assert result[0]["word"] == "HBM3E"

    def test_generate_swot_success(self, sample_articles):
        """Test SWOT generation with mocked response"""
        service = LLMService(api_key="test_key")
        mock_response = json.dumps({
            "strengths": "강한 R&D",
            "weaknesses": "높은 비용",
            "opportunities": "AI 시장",
            "threats": "경쟁 심화",
        })

        with patch.object(service, "_call_claude", return_value=mock_response):
            result = service.generate_swot_analysis("삼성전자", sample_articles)

        assert result["strengths"] == "강한 R&D"
        assert "threats" in result

    def test_generate_interview_questions_success(self, sample_articles):
        """Test interview question generation with mocked response"""
        service = LLMService(api_key="test_key")
        mock_response = json.dumps([{
            "question": "테스트 질문",
            "context": "배경",
            "guide": "가이드",
            "difficulty": "medium",
        }])

        with patch.object(service, "_call_claude", return_value=mock_response):
            result = service.generate_interview_questions(
                "삼성전자", "이력서 내용", sample_articles, num_questions=3,
            )

        assert len(result) == 1
        assert result[0]["question"] == "테스트 질문"

    def test_extract_keywords_invalid_json(self, sample_articles):
        """Test keyword extraction with invalid JSON response"""
        service = LLMService(api_key="test_key")

        with patch.object(service, "_call_claude", return_value="not json"):
            result = service.extract_keywords(sample_articles)

        assert result == []
