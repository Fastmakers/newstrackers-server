"""
Unit tests for news service
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from app.schemas.data_models import NewsArticle
from app.services.news_service import NewsService


class TestNewsService:
    """Test NewsService DB queries"""

    def test_get_articles_returns_results(self, sample_articles):
        """Test: get_articles returns articles from DB"""
        mock_session_factory = MagicMock()
        mock_db = MagicMock()
        mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)

        service = NewsService(session_factory=mock_session_factory)

        # Repository를 mock으로 교체해 domain 객체 직접 반환
        with patch("app.services.news_service.NewsRepository") as MockRepo:
            mock_repo_instance = MagicMock()
            MockRepo.return_value = mock_repo_instance

            # Mock DB rows (NewsArticleDB ORM 객체 흉내)
            mock_rows = []
            for a in sample_articles:
                row = MagicMock()
                row.id = a.id
                row.title = a.title
                row.body = a.body
                row.summary = None
                row.source_name = a.source_name
                row.writer = None
                row.article_url = None
                row.category_l1 = None
                row.category_l2 = a.category_l2
                row.category_l3 = None
                row.published_at = a.published_at
                row.raw_metadata = None
                mock_rows.append(row)

            mock_repo_instance.get_articles_by_keyword.return_value = mock_rows

            result = service.get_articles("반도체")
            assert len(result) == 3

    def test_get_articles_empty_on_error(self):
        """Test: returns empty list on DB error"""
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB Error")
        )

        service = NewsService(session_factory=mock_session_factory)
        result = service.get_articles("반도체")
        assert result == []

    def test_service_initialization(self):
        """Test NewsService can be created"""
        service = NewsService(session_factory=MagicMock())
        assert service is not None


class TestNewsArticle:
    """Test NewsArticle schema (매경 2025 schema)"""

    def test_article_creation(self):
        """Test NewsArticle can be created with new schema"""
        article = NewsArticle(
            id=1,
            title="Test",
            body="Test body",
            source_name="매일경제",
            published_at=datetime(2026, 2, 16),
            category_l2="경제",
        )

        assert article.title == "Test"
        assert article.source_name == "매일경제"
        assert article.body == "Test body"
        assert article.category_l2 == "경제"

    def test_article_backward_compat_properties(self):
        """Test backward-compat properties: .content, .source, .category"""
        article = NewsArticle(
            id=1,
            title="Test",
            body="Test body",
            source_name="매일경제",
            category_l2="경제",
        )

        assert article.content == "Test body"      # .content → .body
        assert article.source == "매일경제"          # .source → .source_name
        assert article.category == "경제"           # .category → .category_l2

    def test_article_serialization(self):
        """Test NewsArticle serialization"""
        article = NewsArticle(
            id=42,
            title="Test",
            body="Test body",
        )

        article_dict = article.model_dump()
        assert article_dict["title"] == "Test"
        assert article_dict["id"] == 42
        assert article_dict["body"] == "Test body"
