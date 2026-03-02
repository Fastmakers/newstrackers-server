"""
Unit tests for analysis nodes and data models.
"""

import pytest

from app.agents.nodes.analysis_nodes import (
    assess_risks,
    compute_monthly_sentiment,
    compute_source_stats,
    extract_news_themes,
    score_five_dimensions,
)
from app.schemas.data_models import IndustryData


class TestIndustryAnalyzer:
    """Test industry analysis nodes"""

    def test_monthly_sentiment_analysis(self, sample_articles):
        """Test monthly sentiment analysis node"""
        state = {"articles": sample_articles, "industry": "반도체", "days_back": 365}
        result = compute_monthly_sentiment(state)
        sentiments = result["monthly_sentiment"]

        assert len(sentiments) > 0
        for sentiment in sentiments:
            assert 0 <= sentiment.intensity <= 10
            assert 0 <= sentiment.score <= 10

    def test_source_stats_computation(self, sample_articles):
        """Test source statistics computation node"""
        state = {"articles": sample_articles, "days_back": 365}
        result = compute_source_stats(state)
        stats = result["source_stats"]

        assert stats.total_articles == len(sample_articles)
        assert stats.date_range_days == 365
        assert len(stats.top_sources) > 0

    def test_empty_analysis(self):
        """Test nodes handle empty articles gracefully"""
        state = {"articles": [], "industry": "반도체", "days_back": 365}

        sentiment_result = compute_monthly_sentiment(state)
        assert sentiment_result["monthly_sentiment"] == []

        stats_result = compute_source_stats(state)
        assert stats_result["source_stats"].total_articles == 0


class TestCompanyAnalyzer:
    """Test company analysis nodes"""

    def test_five_dimension_scoring(self, sample_articles):
        """Test 5-dimension scoring node"""
        state = {"articles": sample_articles, "company": "삼성전자"}
        result = score_five_dimensions(state)
        radar = result["radar_chart"]

        assert len(radar.scores) == 5
        for score in radar.scores:
            assert 0 <= score <= 10

    def test_news_themes_extraction(self, sample_articles):
        """Test news theme extraction node"""
        state = {"articles": sample_articles}
        result = extract_news_themes(state)
        themes = result["news_themes"]

        assert len(themes) > 0
        assert all(isinstance(theme, str) for theme in themes)

    def test_risk_assessment_generation(self, sample_articles):
        """Test risk assessment node"""
        state = {"articles": sample_articles, "company": "삼성전자"}
        result = assess_risks(state)
        assessment = result["risk_assessment"]

        assert assessment.critical_risks is not None
        assert assessment.growth_opportunities is not None
        assert assessment.recommended_focus is not None


class TestDataValidation:
    """Test data model validation"""

    def test_industry_data_validation(self):
        """Test IndustryData validation"""
        with pytest.raises(ValueError):
            IndustryData(
                industry="반도체",
                period={},
                trends=["T1", "T2"],  # Only 2, need 3
                keywords=[],
                monthly_sentiment=[],
            )

    def test_radar_chart_validation(self):
        """Test RadarChart validation"""
        from app.schemas.data_models import RadarChart

        radar = RadarChart(scores=[8, 7, 9, 6, 8])
        assert len(radar.scores) == 5

        with pytest.raises(ValueError):
            RadarChart(scores=[8, 7, 9])  # Only 3

    def test_keyword_type_validation(self):
        """Test Keyword type validation"""
        from app.schemas.data_models import Keyword

        k1 = Keyword(word="test", type="tech", weight=85)
        assert k1.type == "tech"

        with pytest.raises(ValueError):
            Keyword(word="test", type="invalid", weight=85)
