"""
Unit tests for NgramExtractor.

kiwipiepy 로딩 없이 tokenize_batch를 mock으로 대체한다.
"""

from unittest.mock import patch

import pytest

from app.analysis.ngram_extractor import NgramConfig, NgramExtractor


def make_extractor(tokenized_map: dict[str, str]) -> NgramExtractor:
    """
    _tokenize_batch를 mock으로 교체한 NgramExtractor 반환.
    tokenized_map: {원본텍스트: "명사1 명사2 명사3"} 형태.
    """
    extractor = NgramExtractor()

    def mock_tokenize_batch(texts):
        return [tokenized_map.get(t, t) for t in texts]

    extractor._tokenize_batch = mock_tokenize_batch
    return extractor


def make_articles(texts: list[str], category: str = "경제"):
    """(id, body, category_l2) 더미 기사 리스트."""
    return [(i + 1, t, category) for i, t in enumerate(texts)]


# ---------------------------------------------------------------------------
# NgramConfig
# ---------------------------------------------------------------------------

class TestNgramConfig:
    def test_defaults(self):
        cfg = NgramConfig()
        assert cfg.max_features == 1000
        assert cfg.ngram_range == (1, 2)
        assert cfg.min_df == 5
        assert cfg.use_tfidf is True

    def test_custom_values(self):
        cfg = NgramConfig(max_features=200, ngram_range=(2, 2), min_df=2, use_tfidf=False)
        assert cfg.ngram_range == (2, 2)
        assert cfg.use_tfidf is False


# ---------------------------------------------------------------------------
# analyze (전체)
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_empty_articles_returns_zero(self):
        extractor = NgramExtractor()
        report = extractor.analyze([])
        assert report.total_articles == 0
        assert report.keywords == []

    def test_returns_keywords_sorted_by_score(self):
        # min_df=1로 낮춰야 소수 문서에서도 키워드가 추출됨
        cfg = NgramConfig(min_df=1, max_features=50, ngram_range=(1, 1))
        extractor = NgramExtractor(config=cfg)

        # "반도체"가 가장 많이 등장 → 상위 키워드
        texts = [
            "반도체 AI 시장",
            "반도체 수출 증가",
            "반도체 삼성전자 투자",
            "AI 데이터센터",
        ]
        tokenized_map = {t: t for t in texts}
        extractor._tokenize_batch = lambda ts: [tokenized_map.get(t, t) for t in ts]

        articles = make_articles(texts)
        report = extractor.analyze(articles)

        assert report.total_articles == 4
        assert len(report.keywords) > 0
        top_keyword = report.keywords[0].keyword
        assert top_keyword == "반도체"

    def test_keyword_result_has_score(self):
        cfg = NgramConfig(min_df=1, max_features=10, ngram_range=(1, 1))
        extractor = NgramExtractor(config=cfg)
        texts = ["삼성 반도체"] * 5
        extractor._tokenize_batch = lambda ts: ts

        report = extractor.analyze(make_articles(texts))
        for kw in report.keywords:
            assert kw.score > 0


# ---------------------------------------------------------------------------
# analyze_by_category
# ---------------------------------------------------------------------------

class TestAnalyzeByCategory:
    def test_splits_by_category(self):
        cfg = NgramConfig(min_df=1, max_features=50, ngram_range=(1, 1))
        extractor = NgramExtractor(config=cfg)

        articles = [
            (1, "반도체 삼성 투자", "경제"),
            (2, "반도체 SK하이닉스", "경제"),
            (3, "유재석 방송 예능", "방송·TV"),
            (4, "드라마 시청률", "방송·TV"),
        ]
        extractor._tokenize_batch = lambda ts: ts

        report = extractor.analyze_by_category(articles)
        assert "경제" in report.by_category
        assert "방송·TV" in report.by_category

    def test_skips_category_below_min_df(self):
        cfg = NgramConfig(min_df=5, max_features=50, ngram_range=(1, 1))
        extractor = NgramExtractor(config=cfg)

        # 3건 밖에 없는 카테고리 → min_df=5 조건 미충족 → 건너뜀
        articles = [(i, f"텍스트{i}", "소규모카테고리") for i in range(3)]
        extractor._tokenize_batch = lambda ts: ts

        report = extractor.analyze_by_category(articles)
        assert "소규모카테고리" not in report.by_category

    def test_total_articles_counts_all(self):
        cfg = NgramConfig(min_df=1, max_features=50, ngram_range=(1, 1))
        extractor = NgramExtractor(config=cfg)

        articles = make_articles(["텍스트"] * 10, "경제")
        extractor._tokenize_batch = lambda ts: ts

        report = extractor.analyze_by_category(articles)
        assert report.total_articles == 10


# ---------------------------------------------------------------------------
# NgramConfig 통합 — use_tfidf=False (CountVectorizer)
# ---------------------------------------------------------------------------

class TestCountVectorizer:
    def test_count_mode_returns_keywords(self):
        cfg = NgramConfig(min_df=1, max_features=50, ngram_range=(1, 1), use_tfidf=False)
        extractor = NgramExtractor(config=cfg)
        texts = ["반도체 AI"] * 5
        extractor._tokenize_batch = lambda ts: ts

        report = extractor.analyze(make_articles(texts))
        assert len(report.keywords) > 0
