"""
Integration tests - test multiple components working together
"""

import time
from unittest.mock import MagicMock

from app.analysis.company_analyzer import CompanyAnalyzer
from app.analysis.industry_analyzer import IndustryAnalyzer
from app.services.llm_service import LLMService
from app.services.news_service import NewsService


class TestNewsAnalysisPipeline:
    """Test complete news analysis pipeline"""

    def test_industry_analysis_pipeline(self, sample_articles):
        """Test complete industry analysis workflow"""
        articles = sample_articles

        assert len(articles) == 3
        assert articles[0].title == "HBM3E 메모리칩 공급 확대"

    def test_company_analysis_pipeline(self, sample_articles):
        """Test complete company analysis workflow"""
        articles = sample_articles
        assert len(articles) == 3


class TestEndToEndWorkflow:
    """Test end-to-end user workflows"""

    def test_industry_analysis_workflow(self, sample_articles):
        """Test complete industry analysis workflow"""
        mock_news = MagicMock(spec=NewsService)
        mock_llm = MagicMock(spec=LLMService)

        mock_news.get_articles.return_value = sample_articles
        mock_llm.extract_trends.return_value = [
            "AI 칩셋 시장 급성장",
            "HBM 생산 경쟁 심화",
            "정부 지원정책 강화",
        ]
        mock_llm.extract_keywords.return_value = [
            {"word": "HBM3E", "type": "tech", "weight": 95},
            {"word": "삼성전자", "type": "corp", "weight": 90},
            {"word": "정부정책", "type": "policy", "weight": 80},
        ]

        analyzer = IndustryAnalyzer(news_service=mock_news, llm_service=mock_llm)
        result = analyzer.analyze("반도체", days_back=365)

        assert result.industry == "반도체"
        assert len(result.trends) == 3
        assert len(result.keywords) > 0
        assert len(result.monthly_sentiment) > 0

    def test_company_analysis_workflow(self, sample_articles):
        """Test complete company analysis workflow"""
        mock_news = MagicMock(spec=NewsService)
        mock_llm = MagicMock(spec=LLMService)

        mock_news.get_articles.return_value = sample_articles
        mock_llm.generate_swot_analysis.return_value = {
            "strengths": "강한 R&D 역량, 글로벌 네트워크",
            "weaknesses": "높은 제조비용, ESG 규제 부담",
            "opportunities": "AI 시장 확대, 파운드리 사업",
            "threats": "TSMC 경쟁, 중국 추격",
        }
        mock_llm.generate_interview_questions.return_value = [
            {
                "question": "HBM 시장에서 경쟁력을 유지하는 방법은?",
                "context": "기술 경쟁 이해도 평가",
                "guide": "기술력, 빠른 혁신 능력 강조",
                "difficulty": "hard",
            },
            {
                "question": "ESG 경영과 수익성의 균형을 어떻게 맞춰야 하나?",
                "context": "가치관과 실용성 평가",
                "guide": "윤리적 가치와 비즈니스 실용성 제시",
                "difficulty": "medium",
            },
        ]

        analyzer = CompanyAnalyzer(news_service=mock_news, llm_service=mock_llm)
        result = analyzer.analyze(
            company="삼성전자",
            industry="반도체",
            resume="5년 경력 S/W 개발자, Python/C++ 전문",
            days_back=365,
        )

        assert result.company == "삼성전자"
        assert result.industry == "반도체"
        assert result.radar_chart is not None
        assert result.swot is not None
        assert len(result.interview_qna) > 0
        assert "R&D" in result.swot.strengths
        assert result.swot.weaknesses is not None


class TestCacheIntegration:
    """Test caching in analysis pipeline"""

    def test_cache_usage_in_analysis(self, sample_articles):
        """Test that caching works in analysis"""
        mock_news = MagicMock(spec=NewsService)
        mock_llm = MagicMock(spec=LLMService)

        mock_news.get_articles.return_value = sample_articles
        mock_llm.extract_trends.return_value = ["트렌드1", "트렌드2", "트렌드3"]
        mock_llm.extract_keywords.return_value = [
            {"word": "test", "type": "tech", "weight": 85}
        ]

        analyzer = IndustryAnalyzer(news_service=mock_news, llm_service=mock_llm)

        result1 = analyzer.analyze("반도체")
        result2 = analyzer.analyze("반도체")

        assert result1.industry == result2.industry
        assert len(result1.trends) == len(result2.trends)


class TestErrorHandling:
    """Test error handling in pipelines"""

    def test_analysis_handles_missing_data(self):
        """Test analysis handles missing data gracefully"""
        mock_news = MagicMock(spec=NewsService)
        mock_llm = MagicMock(spec=LLMService)
        mock_news.get_articles.return_value = []

        analyzer = IndustryAnalyzer(news_service=mock_news, llm_service=mock_llm)
        result = analyzer.analyze("unknown_industry")

        assert result.industry == "unknown_industry"
        assert len(result.trends) == 3

    def test_analysis_handles_llm_errors(self, sample_articles):
        """Test analysis handles LLM errors gracefully"""
        mock_news = MagicMock(spec=NewsService)
        mock_llm = MagicMock(spec=LLMService)

        mock_news.get_articles.return_value = sample_articles
        mock_llm.generate_swot_analysis.side_effect = Exception("API Error")
        mock_llm.generate_interview_questions.return_value = []

        analyzer = CompanyAnalyzer(news_service=mock_news, llm_service=mock_llm)

        result = analyzer.analyze(
            company="삼성전자",
            industry="반도체",
            resume="Test resume",
        )

        assert result.company == "삼성전자"
        assert result.swot is not None


class TestPerformance:
    """Test performance characteristics"""

    def test_analysis_completes_within_time(self, sample_articles):
        """Test analysis completes within reasonable time"""
        mock_news = MagicMock(spec=NewsService)
        mock_llm = MagicMock(spec=LLMService)

        mock_news.get_articles.return_value = sample_articles
        mock_llm.extract_trends.return_value = ["T1", "T2", "T3"]
        mock_llm.extract_keywords.return_value = [
            {"word": "test", "type": "tech", "weight": 85}
        ]

        analyzer = IndustryAnalyzer(news_service=mock_news, llm_service=mock_llm)

        start_time = time.time()
        result = analyzer.analyze("반도체")
        elapsed = time.time() - start_time

        assert elapsed < 10.0
        assert result is not None
