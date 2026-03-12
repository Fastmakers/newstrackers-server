"""
Integration-style tests for better coverage of services
"""

from unittest.mock import MagicMock

import pytest

from app.schemas.data_models import Keyword
from app.services.llm_service import LLMService
from app.services.news_service import NewsService


class TestDataModels:
    """Test data model functionality"""

    def test_keyword_creation(self):
        """Test keyword model creation"""
        keyword = Keyword(word="테스트", type="tech", weight=85)

        assert keyword.word == "테스트"
        assert keyword.type == "tech"
        assert keyword.weight == 85

    def test_keyword_serialization(self):
        """Test keyword serialization"""
        keyword = Keyword(word="테스트", type="corp", weight=90)

        data = keyword.model_dump()
        assert data["word"] == "테스트"
        assert data["type"] == "corp"
        assert data["weight"] == 90

    def test_keyword_validation(self):
        """Test keyword type validation"""
        for ktype in ["tech", "corp", "policy"]:
            keyword = Keyword(word="test", type=ktype, weight=50)
            assert keyword.type == ktype

        with pytest.raises(ValueError):
            Keyword(word="test", type="invalid", weight=50)


class TestServiceImports:
    """Test that services can be imported and initialized"""

    def test_llm_service_init(self):
        """Test LLM service initialization"""
        service = LLMService(api_key="test_key")
        assert service.api_key == "test_key"
        assert service.model == "claude-sonnet-4-6"

    def test_news_service_init(self):
        """Test News service initialization"""
        service = NewsService(session_factory=MagicMock())
        assert service is not None
        assert hasattr(service, "get_articles")
        assert hasattr(service, "hybrid_search")
