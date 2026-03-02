"""
TF-IDF 기반 N-gram 키워드 추출기.

kiwipiepy로 명사를 추출한 뒤 scikit-learn TfidfVectorizer로
산업·카테고리별 핵심 키워드(단어 + 바이그램)를 뽑는다.

사용 예:
    extractor = NgramExtractor()
    result = extractor.analyze(articles)          # 전체
    by_cat  = extractor.analyze_by_category(articles)  # 카테고리별
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

from app.analysis.text_cleaner import TextCleaner

logger = logging.getLogger(__name__)


@dataclass
class NgramConfig:
    """N-gram 분석 파라미터 (config.yaml 대신 dataclass로 관리)."""
    max_features: int = 1000    # 상위 N개 키워드만
    ngram_range: tuple[int, int] = (1, 2)   # 1-gram + 2-gram (바이그램)
    min_df: int = 5             # 최소 5개 기사에서 등장해야 유효
    use_tfidf: bool = True      # False면 단순 빈도(CountVectorizer)


@dataclass
class KeywordResult:
    """단건 키워드 추출 결과."""
    keyword: str
    score: float


@dataclass
class NgramReport:
    """analyze() / analyze_by_category() 반환 타입."""
    total_articles: int
    config: NgramConfig
    keywords: list[KeywordResult] = field(default_factory=list)
    # 카테고리별 결과: {category_l2: [KeywordResult, ...]}
    by_category: dict[str, list[KeywordResult]] = field(default_factory=dict)


class NgramExtractor:
    """
    TF-IDF + kiwipiepy 명사 추출 기반 N-gram 키워드 추출기.

    Parameters
    ----------
    config : NgramConfig, optional
        분석 파라미터. 기본값 사용 가능.
    """

    # kiwipiepy에서도 거를 불용어 (조사·바이라인 잔재·숫자 단위 등)
    _STOPWORDS = frozenset([
        "기자", "특파원", "논설위원", "것", "수", "등", "및", "의",
        "이", "가", "을", "를", "은", "는", "에", "도", "로", "에서",
        "에게", "년", "월", "일", "원", "개", "명", "번", "호",
        "뉴스", "매경", "매일경제", "씨", "씩", "만큼", "따르면",
    ])

    def __init__(self, config: NgramConfig | None = None):
        self.config = config or NgramConfig()
        self._cleaner = TextCleaner()
        self._kiwi = None  # lazy init

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def analyze(self, articles) -> NgramReport:
        """
        기사 전체 대상 TF-IDF N-gram 분석.

        articles: list[NewsArticle] 또는 [(id, body), ...] 또는
                  [(id, body, category_l2), ...] 형태 모두 지원.
        """
        texts = self._extract_texts(articles)
        if not texts:
            return NgramReport(total_articles=0, config=self.config)

        tokenized = self._tokenize_batch(texts)
        keywords = self._fit_and_rank(tokenized)

        return NgramReport(
            total_articles=len(texts),
            config=self.config,
            keywords=keywords,
        )

    def analyze_by_category(self, articles) -> NgramReport:
        """
        카테고리(category_l2)별로 분리해 TF-IDF 분석.

        articles: list[NewsArticle] 또는 [(id, body, category_l2), ...] 형태.
        """
        # 카테고리별 텍스트 분류
        cat_texts: dict[str, list[str]] = {}
        for article in articles:
            if hasattr(article, "body"):
                body = article.body or ""
                cat = article.category_l2 or "미분류"
            elif len(article) >= 3:
                body = article[1] or ""
                cat = article[2] or "미분류"
            else:
                body = article[1] or ""
                cat = "미분류"
            cat_texts.setdefault(cat, []).append(body)

        total = sum(len(v) for v in cat_texts.values())
        report = NgramReport(total_articles=total, config=self.config)

        for cat, texts in cat_texts.items():
            if len(texts) < self.config.min_df:
                logger.debug("카테고리 '%s' 기사 수 부족(%d건), 건너뜀", cat, len(texts))
                continue
            tokenized = self._tokenize_batch(texts)
            report.by_category[cat] = self._fit_and_rank(tokenized)
            logger.info("카테고리 '%s' 완료: 상위 키워드 %d개", cat, len(report.by_category[cat]))

        return report

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    @property
    def kiwi(self):
        if self._kiwi is None:
            from kiwipiepy import Kiwi
            logger.info("Kiwi 모델 로딩 중...")
            self._kiwi = Kiwi()
            logger.info("Kiwi 로딩 완료")
        return self._kiwi

    def _extract_texts(self, articles) -> list[str]:
        texts = []
        for article in articles:
            if hasattr(article, "body"):
                texts.append(article.body or "")
            else:
                texts.append(article[1] or "")
        return texts

    def _tokenize_batch(self, texts: list[str]) -> list[str]:
        """
        텍스트 목록 → 정제 → 명사 추출 → 공백 구분 문자열 목록.
        TfidfVectorizer에 넣기 위해 각 문서를 단일 문자열로 반환.
        """
        cleaned = self._cleaner.clean_batch(texts)
        placeholders = [t if (t and t.strip()) else " " for t in cleaned]
        results = self.kiwi.tokenize(placeholders)

        tokenized = []
        for result in results:
            nouns = [
                tok.form for tok in result
                if tok.tag in ("NNG", "NNP")
                and len(tok.form) > 1
                and tok.form not in self._STOPWORDS
            ]
            tokenized.append(" ".join(nouns))
        return tokenized

    def _fit_and_rank(self, tokenized_docs: list[str]) -> list[KeywordResult]:
        """TF-IDF (또는 Count) 벡터화 → 상위 키워드 리스트 반환."""
        cfg = self.config
        VectorizerCls = TfidfVectorizer if cfg.use_tfidf else CountVectorizer

        vectorizer = VectorizerCls(
            ngram_range=cfg.ngram_range,
            max_features=cfg.max_features,
            min_df=cfg.min_df,
        )

        try:
            dtm = vectorizer.fit_transform(tokenized_docs)
        except ValueError:
            # min_df 조건을 만족하는 단어가 없을 때
            return []

        vocab = vectorizer.get_feature_names_out()
        scores = np.asarray(dtm.sum(axis=0)).ravel()

        ranked = sorted(zip(vocab, scores), key=lambda x: x[1], reverse=True)
        return [KeywordResult(keyword=kw, score=float(sc)) for kw, sc in ranked]
