"""
Unit tests for LexicalDiversityAnalyzer.

kiwipiepy는 무거우므로 tokenize()를 mock으로 처리한다.
"""

import math
from unittest.mock import MagicMock, patch

import pytest

from app.analysis.lexical_diversity import (
    ArticleLexStats,
    LexicalDiversityAnalyzer,
    LexicalDiversityReport,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_analyzer(tokens_map: dict[int, list[str]]) -> LexicalDiversityAnalyzer:
    """tokenize_batch()를 mock으로 주입한 Analyzer 반환 (kiwipiepy 로딩 없음)."""
    analyzer = LexicalDiversityAnalyzer()
    analyzer.tokenize = lambda text: tokens_map.get(int(text), [])
    analyzer.tokenize_batch = lambda texts: [tokens_map.get(int(t), []) for t in texts]
    return analyzer


def make_articles(tokens_map: dict[int, list[str]]):
    """(id, str(id)) 형태 더미 기사 리스트 반환."""
    return [(article_id, str(article_id)) for article_id in tokens_map]


# ---------------------------------------------------------------------------
# calc_log_ttr
# ---------------------------------------------------------------------------

class TestCalcLogTTR:

    def test_normal_text(self):
        # min_tokens=10으로 낮게 지정해 20-token 입력이 None 안 되게
        analyzer = LexicalDiversityAnalyzer(min_tokens=10)
        # 20 tokens, 10 unique → log(10)/log(20) ≈ 0.769
        tokens = [str(i) for i in range(10)] * 2
        result = analyzer.calc_log_ttr(tokens)
        expected = math.log(10) / math.log(20)
        assert result == pytest.approx(expected, rel=1e-5)

    def test_below_min_tokens_returns_none(self):
        analyzer = LexicalDiversityAnalyzer(min_tokens=50)
        tokens = ["단어"] * 30   # 30 < 50 → None
        assert analyzer.calc_log_ttr(tokens) is None

    def test_all_same_tokens_returns_none(self):
        analyzer = LexicalDiversityAnalyzer()
        tokens = ["반복"] * 60   # 60 ≥ 50 but types == 1 → None
        assert analyzer.calc_log_ttr(tokens) is None  # types == 1

    def test_all_unique_tokens(self):
        analyzer = LexicalDiversityAnalyzer()
        tokens = [str(i) for i in range(50)]  # 50 unique out of 50 (≥ min_tokens)
        result = analyzer.calc_log_ttr(tokens)
        assert result == pytest.approx(1.0, rel=1e-5)


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

class TestAnalyze:

    def test_normal_articles_not_noise(self):
        """다양한 어휘를 가진 기사는 노이즈로 분류되지 않아야 함."""
        # 60 tokens, 40 unique → log(40)/log(60) ≈ 0.906  → 정상 범위(0.82~0.99)
        tokens_map = {
            1: [f"w{i}" for i in range(40)] + [f"w{i}" for i in range(20)],
            2: [f"w{i}" for i in range(35)] + [f"w{i}" for i in range(15)],
            3: [f"w{i}" for i in range(30)] + [f"w{i}" for i in range(20)],
        }
        analyzer = make_analyzer(tokens_map)
        articles = make_articles(tokens_map)
        report = analyzer.analyze(articles)

        assert report.total_articles == 3
        assert report.analyzed_articles == 3
        # 절대값 threshold(0.82~0.99) 안에 있으므로 노이즈 0
        assert report.noise_count == 0

    def test_short_article_is_noise(self):
        """토큰 부족 기사는 노이즈로 분류돼야 함."""
        tokens_map = {
            1: ["단어"] * 3,   # 3 tokens < min_tokens(50)
        }
        analyzer = make_analyzer(tokens_map)
        report = analyzer.analyze(make_articles(tokens_map))

        assert report.stats[0].is_noise is True
        assert "토큰 부족" in report.stats[0].noise_reason

    def test_extreme_repeat_is_noise(self):
        """완전 반복 기사(types=1)는 노이즈로 분류돼야 함."""
        tokens_map = {
            1: ["삼성전자"] * 60,  # 60 tokens, 1 unique → log_ttr = None
        }
        analyzer = make_analyzer(tokens_map)
        report = analyzer.analyze(make_articles(tokens_map))

        assert report.stats[0].is_noise is True
        assert "어휘 단일화" in report.stats[0].noise_reason

    def test_low_log_ttr_is_noise(self):
        """절대값 low_threshold 미만 기사는 노이즈로 분류돼야 함."""
        # 60 tokens, 5 unique → log(5)/log(60) ≈ 0.393 < 0.82
        tokens_map = {1: [f"w{i % 5}" for i in range(60)]}
        analyzer = make_analyzer(tokens_map)
        report = analyzer.analyze(make_articles(tokens_map))

        assert report.stats[0].is_noise is True
        assert "반복 패턴" in report.stats[0].noise_reason

    def test_threshold_can_be_customized(self):
        """low_threshold / high_threshold를 생성자로 조정할 수 있어야 함."""
        # 60 tokens, 20 unique → log(20)/log(60) ≈ 0.732  (기본 0.82 미만이라 노이즈)
        tokens_map = {1: [f"w{i % 20}" for i in range(60)]}
        # 임계값을 0.5로 낮추면 0.732 > 0.5 이므로 노이즈 아님
        analyzer = LexicalDiversityAnalyzer(low_threshold=0.5, high_threshold=0.99)
        analyzer.tokenize_batch = lambda texts: [tokens_map.get(int(t), []) for t in texts]
        report = analyzer.analyze(make_articles(tokens_map))

        assert report.stats[0].is_noise is False

    def test_empty_articles(self):
        report = LexicalDiversityAnalyzer().analyze([])
        assert report.total_articles == 0
        assert report.analyzed_articles == 0
        assert report.noise_count == 0

    def test_report_statistics(self):
        """평균·표준편차·p5·p95 계산이 맞는지 확인."""
        # 10개 기사, log_ttr이 일정하게 퍼져 있도록 설계
        tokens_map = {}
        for i in range(1, 11):
            n = 50 + i * 5          # 55~100 tokens
            u = 10 + i * 3          # 13~40 unique
            tokens_map[i] = [f"w{j}" for j in range(u)] + [f"w{j}" for j in range(n - u)]

        analyzer = make_analyzer(tokens_map)
        report = analyzer.analyze(make_articles(tokens_map))

        assert report.analyzed_articles == 10
        assert 0 < report.log_ttr_mean < 1.0
        assert report.log_ttr_p5 <= report.log_ttr_mean <= report.log_ttr_p95


# ---------------------------------------------------------------------------
# noise_article_ids
# ---------------------------------------------------------------------------

class TestNoiseArticleIds:

    def test_returns_only_noise_ids(self):
        stats = [
            ArticleLexStats(article_id=1, token_count=5, type_count=5, log_ttr=None, is_noise=True),
            ArticleLexStats(article_id=2, token_count=50, type_count=40, log_ttr=0.9, is_noise=False),
            ArticleLexStats(article_id=3, token_count=50, type_count=3, log_ttr=0.3, is_noise=True),
        ]
        report = LexicalDiversityReport(
            total_articles=3, analyzed_articles=2, noise_count=2,
            noise_ratio=2/3, log_ttr_mean=0.6, log_ttr_std=0.1,
            log_ttr_p5=0.5, log_ttr_p95=0.95, stats=stats,
        )
        analyzer = LexicalDiversityAnalyzer()
        noise_ids = analyzer.noise_article_ids(report)
        assert set(noise_ids) == {1, 3}
