"""
NewsService — 검색 오케스트레이션.

파이프라인별 검색 경로:
    V1 (Baseline):   embed_query → vector_search (Top K)
    V2 (Hybrid):     embed_query ‖ keyword_search → RRF → Top K
    V3 (Reranker):   embed_query ‖ keyword_search → RRF Top 20 → Cross-Encoder → Top K
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.db.adapters.news_adapter import article_row_to_domain, chunk_row_to_domain
from app.db.repositories.news_repository import NewsRepository
from app.schemas.data_models import NewsArticle, NewsChunk
from app.services.search.rrf import rrf_fuse

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"

# V3: Cross-Encoder에 전달할 RRF 후보 수
_V3_RERANK_POOL = 20


class NewsService:
    """뉴스 검색 서비스 — 읽기 전용."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        self._openai_client = None
        self._reranker = None  # Lazy-load (V3 첫 호출 시)

    @property
    def session_factory(self):
        if self._session_factory is None:
            from app.db.base import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    def _repo(self):
        return self.session_factory()

    # -------------------------------------------------------------------------
    # 공개 검색 API
    # -------------------------------------------------------------------------

    def vector_search(
        self,
        query: str,
        category_l2: Optional[str] = None,
        top_k: int = 5,
    ) -> list[NewsChunk]:
        """V1 Baseline — 벡터 유사도 검색만 수행.

        Args:
            query:       자소서 원문 (임베딩 후 코사인 유사도 검색)
            category_l2: 카테고리 필터
            top_k:       반환 청크 수
        """
        embedding = self.embed_query(query)
        return self._vector_search_chunks(embedding, category_l2, limit=top_k)

    def hybrid_search(
        self,
        query: str,
        category_l2: Optional[str] = None,
        top_k: int = 5,
        use_reranker: bool = False,
    ) -> list[NewsChunk]:
        """V2/V3 — 하이브리드 검색 (벡터 + pg_trgm → RRF → optional Cross-Encoder).

        병렬 처리:
            embed_query ──────────────► vector_search ─┐
            keyword_search (pg_trgm) ──────────────────┤► RRF
                                                        │
            V3: ────────────────────────────────────────┤► Cross-Encoder ► Top K
            V2: ────────────────────────────────────────┘► Top K

        Args:
            query:        Haiku가 변환한 압축 쿼리 (v2/v3)
            top_k:        최종 반환 청크 수
            use_reranker: True = V3 (RRF Top 20 → Cross-Encoder), False = V2 (RRF Top K)
        """
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_embed = executor.submit(self.embed_query, query)
            future_keyword = executor.submit(self._keyword_search_chunks, query, category_l2)

            embedding = future_embed.result()
            future_vector = executor.submit(self._vector_search_chunks, embedding, category_l2)

            keyword_chunks = future_keyword.result()
            vector_chunks = future_vector.result()

        fused = rrf_fuse(vector_chunks, keyword_chunks, top_n=100)

        if use_reranker:
            rerank_pool = fused[:_V3_RERANK_POOL]
            return self._get_reranker().rerank(query, rerank_pool, top_n=top_k)

        return fused[:top_k]

    def get_articles(
        self,
        query: str,
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[NewsArticle]:
        """키워드 기반 기사 검색 (분석 엔드포인트용)."""
        try:
            with self._repo() as db:
                repo = NewsRepository(db)
                rows = repo.get_articles_by_keyword(query, category_l2, limit)
                return [article_row_to_domain(r) for r in rows]
        except Exception as e:
            logger.error("키워드 검색 오류: %s", e)
            return []

    def count_articles(self) -> int:
        try:
            from sqlalchemy import text
            with self._repo() as db:
                return db.execute(text("SELECT COUNT(*) FROM news_articles")).scalar_one()
        except Exception as e:
            logger.error("카운트 오류: %s", e)
            return 0

    # -------------------------------------------------------------------------
    # 임베딩
    # -------------------------------------------------------------------------

    def embed_query(self, text: str) -> list[float]:
        """쿼리 텍스트 → OpenAI 임베딩 벡터 (text-embedding-3-small)."""
        from app.core.config import settings
        from openai import OpenAI
        if self._openai_client is None:
            if not settings.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
            self._openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = self._openai_client.embeddings.create(model=EMBEDDING_MODEL, input=text)
        return response.data[0].embedding

    # -------------------------------------------------------------------------
    # 내부 검색 헬퍼 (각자 독립 DB 세션)
    # -------------------------------------------------------------------------

    def _keyword_search_chunks(
        self,
        query: str,
        category_l2: Optional[str] = None,
    ) -> list[NewsChunk]:
        """pg_trgm word_similarity 키워드 검색."""
        try:
            with self._repo() as db:
                pairs = NewsRepository(db).search_chunks_by_keyword(
                    query, category_l2, limit=100
                )
                return [chunk_row_to_domain(c, article_row_to_domain(a)) for c, a in pairs]
        except Exception as e:
            logger.error("키워드 검색 오류: %s", e)
            return []

    def _vector_search_chunks(
        self,
        embedding: list[float],
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[NewsChunk]:
        """코사인 유사도 벡터 검색."""
        try:
            with self._repo() as db:
                pairs = NewsRepository(db).search_chunks_by_vector(
                    embedding, category_l2, limit=limit
                )
                return [chunk_row_to_domain(c, article_row_to_domain(a)) for c, a in pairs]
        except Exception as e:
            logger.error("벡터 검색 오류: %s", e)
            return []

    def _get_reranker(self):
        """Cross-Encoder 리랭커 — 첫 호출 시 lazy-load."""
        if self._reranker is None:
            from app.services.search.reranker import CrossEncoderReranker
            self._reranker = CrossEncoderReranker()
        return self._reranker
