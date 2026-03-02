"""
Cross-Encoder 리랭커 — RRF 후보 30건 → top_k 재정렬.

모델: BAAI/bge-reranker-m3 (다국어, 한국어 지원)
의존성: sentence-transformers

Lazy-load: 첫 rerank() 호출 시 모델을 메모리에 올린다.
추론 입력은 최대 30건으로 제한해 지연 시간 예측 가능하게 유지.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.data_models import NewsChunk

logger = logging.getLogger(__name__)

MODEL_ID = "BAAI/bge-reranker-m3"


class CrossEncoderReranker:
    """Cross-Encoder 기반 의미 리랭커.

    사용 예:
        reranker = CrossEncoderReranker()
        top10 = reranker.rerank(query, rrf_top30, top_n=10)
    """

    def __init__(self):
        self._model = None

    @property
    def model(self):
        """sentence_transformers.CrossEncoder — 첫 접근 시 로드."""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(MODEL_ID)
                logger.info("CrossEncoder 로드 완료: %s", MODEL_ID)
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers 패키지가 필요합니다.\n"
                    "  uv add sentence-transformers"
                ) from exc
        return self._model

    def rerank(
        self,
        query: str,
        chunks: list[NewsChunk],
        top_n: int = 10,
    ) -> list[NewsChunk]:
        """chunks를 query 관련도 순으로 재정렬하여 top_n개 반환.

        Args:
            query: 검색 쿼리 (원문 또는 transform_query 결과)
            chunks: RRF 정렬된 후보 청크 (최대 30건 권장)
            top_n: 반환할 상위 청크 수

        Returns:
            Cross-Encoder 점수 내림차순으로 정렬된 chunks[:top_n]
            모델 오류 시 RRF 순서 그대로 반환 (fallback)
        """
        if not chunks:
            return []

        try:
            pairs = [(query, chunk.chunk_text) for chunk in chunks]
            scores = self.model.predict(pairs)
            ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
            return [chunk for _, chunk in ranked[:top_n]]
        except Exception as exc:
            logger.error("CrossEncoder 리랭킹 실패, RRF 순서 유지: %s", exc)
            return chunks[:top_n]
