"""
어휘 다양성 분석기 — LogTTR (Herdan's C) 기반 노이즈 기사 탐지.

SPEC: docs/SPEC_SEARCH.md (데이터 품질 필터링)

파이프라인:
    1. kiwipiepy로 기사 본문에서 명사 추출 → TOKENIZED_TEXT
    2. Token(총 단어 수) / Type(고유 단어 수) 계산
    3. LogTTR = log(Types) / log(Tokens)  — 길이 편향 보정 (Herdan's C)
    4. 분포의 하위 5% (반복 스팸) / 상위 5% (파싱 오류) → 노이즈로 분류

LogTTR 범위 (매경 2025 기준, mean=0.914 std=0.030):
    - 정상: 0.82 ~ 0.99
    - 낮음 (< LOW_THRESHOLD=0.82): 반복 패턴 기사 → RAG 품질 저하
    - 높음 (> HIGH_THRESHOLD=0.99): 파싱 오류, 해시값, 극단적 단신 → 모델 오염

    p5/p95 상대 기준 대신 절대값 threshold를 사용하는 이유:
    매경 뉴스처럼 이미 편집된 언론사 데이터는 LogTTR 분포가 매우 좁아
    (std≈0.03) p5/p95가 정상 기사를 10%나 과탐지한다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_MIN_TOKENS = 50      # 이 미만은 RAG 문맥으로 의미 없음 (단신·캡션 제거)
_LOW_THRESHOLD = 0.82  # 이 미만 = 반복 패턴 의심 (mean - ~3σ 기준)
_HIGH_THRESHOLD = 0.99 # 이 초과 = 파싱 오류 / 극단적 단신 의심


@dataclass
class ArticleLexStats:
    """기사 1건의 어휘 통계."""
    article_id: int
    token_count: int
    type_count: int
    log_ttr: Optional[float]        # None = 토큰 부족
    is_noise: bool = False          # 노이즈 여부 (분포 기반 판정 후 세팅)
    noise_reason: Optional[str] = None


@dataclass
class LexicalDiversityReport:
    """전체 분석 결과 요약."""
    total_articles: int
    analyzed_articles: int          # 토큰 수 충족 기사
    noise_count: int
    noise_ratio: float              # noise_count / analyzed_articles
    log_ttr_mean: float
    log_ttr_std: float
    log_ttr_p5: float               # 하위 5% 분위수 (참고용, 필터링 기준 아님)
    log_ttr_p95: float              # 상위 5% 분위수 (참고용, 필터링 기준 아님)
    stats: list[ArticleLexStats] = field(default_factory=list)


class LexicalDiversityAnalyzer:
    """
    kiwipiepy 명사 추출 → LogTTR 계산 → 노이즈 필터링.

    사용 예:
        analyzer = LexicalDiversityAnalyzer()
        report = analyzer.analyze(articles)   # articles: list[NewsArticle]
        noise_ids = analyzer.noise_article_ids(report)
    """

    def __init__(
        self,
        min_tokens: int = _MIN_TOKENS,
        low_threshold: float = _LOW_THRESHOLD,
        high_threshold: float = _HIGH_THRESHOLD,
    ):
        self.min_tokens = min_tokens
        self.low_threshold = low_threshold    # 이 미만 → 반복 스팸 의심
        self.high_threshold = high_threshold  # 이 초과 → 파싱 오류 의심
        self._kiwi = None   # lazy init (무거운 모델, 필요할 때만 로드)

    @property
    def kiwi(self):
        if self._kiwi is None:
            from kiwipiepy import Kiwi
            logger.info("Kiwi 모델 로딩 중...")
            self._kiwi = Kiwi()
            logger.info("Kiwi 로딩 완료")
        return self._kiwi

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def tokenize(self, text: str) -> list[str]:
        """본문 텍스트 → 명사 리스트 (kiwipiepy NNG/NNP)."""
        if not text or not text.strip():
            return []
        tokens = self.kiwi.tokenize(text)
        return [t.form for t in tokens if t.tag in ("NNG", "NNP")]

    def tokenize_batch(self, texts: list[str]) -> list[list[str]]:
        """텍스트 목록을 한 번에 토크나이징 (멀티스레드 병렬 처리).

        단건 tokenize() 반복 대비 ~3~5배 빠름.
        """
        # 빈 텍스트는 빈 자리 표시자로 치환 후 나중에 복원
        placeholders = [t if (t and t.strip()) else " " for t in texts]
        results = self.kiwi.tokenize(placeholders)
        return [
            [tok.form for tok in result if tok.tag in ("NNG", "NNP")]
            for result in results
        ]

    def calc_log_ttr(self, tokens: list[str]) -> Optional[float]:
        """LogTTR = log(Types) / log(Tokens). 토큰 부족시 None."""
        n = len(tokens)
        if n < self.min_tokens:
            return None
        types = len(set(tokens))
        if types <= 1 or n <= 1:
            return None
        return math.log(types) / math.log(n)

    def analyze(self, articles) -> LexicalDiversityReport:
        """
        기사 리스트 → LexicalDiversityReport.

        articles: list[NewsArticle] 또는 [(id, body_text), ...] 형태도 지원.
        배치 처리로 토크나이징 (~3~5배 빠름).
        """
        if not articles:
            return self._build_report([])

        ids: list[int] = []
        texts: list[str] = []
        for article in articles:
            if hasattr(article, "id"):
                ids.append(article.id)
                texts.append(article.body or "")
            else:
                ids.append(article[0])
                texts.append(article[1])

        token_lists = self.tokenize_batch(texts)

        stats_list = [
            ArticleLexStats(
                article_id=article_id,
                token_count=len(tokens),
                type_count=len(set(tokens)),
                log_ttr=self.calc_log_ttr(tokens),
            )
            for article_id, tokens in zip(ids, token_lists)
        ]
        return self._build_report(stats_list)

    def noise_article_ids(self, report: LexicalDiversityReport) -> list[int]:
        """노이즈로 분류된 기사 ID 목록."""
        return [s.article_id for s in report.stats if s.is_noise]

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _build_report(self, stats_list: list[ArticleLexStats]) -> LexicalDiversityReport:
        valid = [s for s in stats_list if s.log_ttr is not None]
        total = len(stats_list)
        analyzed = len(valid)

        # log_ttr=None 항목은 유효 분포와 무관하게 항상 노이즈로 먼저 표시
        noise_count = 0
        for s in stats_list:
            if s.log_ttr is None:
                s.is_noise = True
                if s.token_count < self.min_tokens:
                    s.noise_reason = f"토큰 부족 ({s.token_count}개 < {self.min_tokens})"
                else:
                    s.noise_reason = f"어휘 단일화 (type={s.type_count}) — 극단적 반복"
                noise_count += 1

        if analyzed == 0:
            logger.warning("분석 가능한 기사가 없습니다.")
            return LexicalDiversityReport(
                total_articles=total,
                analyzed_articles=0,
                noise_count=noise_count,
                noise_ratio=noise_count / total if total else 0.0,
                log_ttr_mean=0.0,
                log_ttr_std=0.0,
                log_ttr_p5=0.0,
                log_ttr_p95=1.0,
                stats=stats_list,
            )

        values = [s.log_ttr for s in valid]

        mean = sum(values) / analyzed
        variance = sum((v - mean) ** 2 for v in values) / analyzed
        std = math.sqrt(variance)

        # 절대값 threshold 기반 노이즈 분류
        # p5/p95 상대 기준은 좁은 분포(std≈0.03)에서 정상 기사를 과탐지함
        low = self.low_threshold
        high = self.high_threshold

        for s in stats_list:
            if s.log_ttr is None:
                pass  # 이미 위에서 처리됨
            elif s.log_ttr < low:
                s.is_noise = True
                s.noise_reason = (
                    f"LogTTR 낮음 ({s.log_ttr:.4f} < {low}) — 반복 패턴 의심"
                )
                noise_count += 1
            elif s.log_ttr > high:
                s.is_noise = True
                s.noise_reason = (
                    f"LogTTR 높음 ({s.log_ttr:.4f} > {high}) — 파싱 오류 / 극단적 단신 의심"
                )
                noise_count += 1

        # 분포 참고용 분위수 계산 (필터링에는 미사용)
        sorted_vals = sorted(values)
        p5_idx = max(0, int(analyzed * 0.05) - 1)
        p95_idx = min(analyzed - 1, int(analyzed * 0.95))
        p5 = sorted_vals[p5_idx]
        p95 = sorted_vals[p95_idx]

        return LexicalDiversityReport(
            total_articles=total,
            analyzed_articles=analyzed,
            noise_count=noise_count,
            noise_ratio=noise_count / analyzed if analyzed else 0.0,
            log_ttr_mean=round(mean, 4),
            log_ttr_std=round(std, 4),
            log_ttr_p5=round(p5, 4),    # 참고용
            log_ttr_p95=round(p95, 4),  # 참고용
            stats=stats_list,
        )
