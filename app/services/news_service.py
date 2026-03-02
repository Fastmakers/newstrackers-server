"""
NewsService — 검색 오케스트레이션.

SPEC: docs/SPEC_SEARCH.md §4
- 1단계: 임베딩 생성 ‖ 키워드 검색 (병렬, ThreadPoolExecutor)  ✅
- 2단계: 벡터 검색 (임베딩 완료 후 즉시 시작)                  ✅
- 3단계: RRF 융합 → top 30 후보                                ✅
- 4단계: Cross-Encoder 리랭킹 → top_k (ENABLE_RERANKER=true 시) ✅
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from app.core.config import settings
from app.db.adapters.news_adapter import article_row_to_domain, chunk_row_to_domain
from app.db.repositories.news_repository import NewsRepository
from app.schemas.data_models import NewsArticle, NewsChunk
from app.services.search.rrf import rrf_fuse

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"

# Cross-Encoder 입력 후보 수 (RRF top-N → reranker)
_RERANK_POOL_SIZE = 30


class NewsService:
    """Read-only 뉴스 검색 서비스."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        self._openai_client = None
        self._reranker = None
        if settings.ENABLE_RERANKER:
            from app.services.search.reranker import CrossEncoderReranker
            self._reranker = CrossEncoderReranker()

    @property
    def session_factory(self):
        if self._session_factory is None:
            from app.db.base import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    def _repo(self):
        return self.session_factory()

    # -------------------------------------------------------------------------
    # 공개 API
    # -------------------------------------------------------------------------

    def hybrid_search(
        self,
        query: str,
        category_l2: Optional[str] = None,
        top_k: int = 5,
    ) -> list[NewsChunk]:
        """4단계 하이브리드 검색 (SPEC §4).

        병렬 처리:
            embed_query ──────────────► vector_search ─┐
            keyword_search (pg_trgm) ──────────────────┤► RRF ► Cross-Encoder ► top_k
        """
        with ThreadPoolExecutor(max_workers=3) as executor:
            # 임베딩 + 키워드 검색 동시 시작
            future_embed = executor.submit(self.embed_query, query)
            future_keyword = executor.submit(
                self._keyword_search_chunks, query, category_l2
            )

            # 임베딩이 완료되면 즉시 벡터 검색 시작
            embedding = future_embed.result()
            future_vector = executor.submit(
                self._vector_search_chunks, embedding, category_l2
            )

            keyword_chunks = future_keyword.result()
            vector_chunks = future_vector.result()

        # RRF 융합 → top 30 후보
        fused = rrf_fuse(vector_chunks, keyword_chunks, top_n=100)
        rerank_pool = fused[:_RERANK_POOL_SIZE]

        # Cross-Encoder 리랭킹 (활성화된 경우)
        if self._reranker is not None:
            return self._reranker.rerank(query, rerank_pool, top_n=top_k)

        return rerank_pool[:top_k]

    def get_articles(
        self,
        query: str,
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[NewsArticle]:
        """키워드 기반 기사 검색 (SPEC §4-1 키워드 검색)."""
        try:
            with self._repo() as db:
                repo = NewsRepository(db)
                rows = repo.get_articles_by_keyword(query, category_l2, limit)
                return [article_row_to_domain(r) for r in rows]
        except Exception as e:
            logger.error(f"키워드 검색 오류: {e}")
            return []

    def search_by_text(
        self,
        query: str,
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[NewsChunk]:
        """쿼리 텍스트 → 임베딩 → 벡터 유사도 청크 검색 (SPEC §4-1 벡터 검색)."""
        try:
            embedding = self.embed_query(query)
            return self.search_similar(embedding, category_l2=category_l2, limit=limit)
        except Exception as e:
            logger.error(f"텍스트 벡터 검색 오류: {e}")
            return []

    def search_similar(
        self,
        embedding: list[float],
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[NewsChunk]:
        """임베딩 벡터 → 코사인 유사도 청크 검색 (SPEC §4-1)."""
        try:
            with self._repo() as db:
                repo = NewsRepository(db)
                pairs = repo.search_chunks_by_vector(embedding, category_l2, limit)
                return [
                    chunk_row_to_domain(chunk, article_row_to_domain(article))
                    for chunk, article in pairs
                ]
        except Exception as e:
            logger.error(f"벡터 검색 오류: {e}")
            return []

    def count_articles(self) -> int:
        try:
            with self._repo() as db:
                return NewsRepository(db).count_articles()
        except Exception as e:
            logger.error(f"카운트 오류: {e}")
            return 0

    # -------------------------------------------------------------------------
    # 병렬 검색 헬퍼 (각자 독립 DB 세션)
    # -------------------------------------------------------------------------

    def _keyword_search_chunks(
        self,
        query: str,
        category_l2: Optional[str] = None,
    ) -> list[NewsChunk]:
        """pg_trgm 키워드 검색 — 독립 DB 세션."""
        try:
            with self._repo() as db:
                pairs = NewsRepository(db).search_chunks_by_keyword(
                    query, category_l2, limit=100
                )
                return [
                    chunk_row_to_domain(c, article_row_to_domain(a))
                    for c, a in pairs
                ]
        except Exception as e:
            logger.error("키워드 검색 오류: %s", e)
            return []

    def _vector_search_chunks(
        self,
        embedding: list[float],
        category_l2: Optional[str] = None,
    ) -> list[NewsChunk]:
        """벡터 검색 — 독립 DB 세션."""
        try:
            with self._repo() as db:
                pairs = NewsRepository(db).search_chunks_by_vector(
                    embedding, category_l2, limit=100
                )
                return [
                    chunk_row_to_domain(c, article_row_to_domain(a))
                    for c, a in pairs
                ]
        except Exception as e:
            logger.error("벡터 검색 오류: %s", e)
            return []

    # -------------------------------------------------------------------------
    # 임베딩
    # -------------------------------------------------------------------------

    def embed_query(self, text: str) -> list[float]:
        """쿼리 텍스트 → OpenAI 임베딩 벡터 (SPEC §4-1)."""
        client = self._get_openai_client()
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
        return response.data[0].embedding

    def _get_openai_client(self):
        if self._openai_client is None:
            from openai import OpenAI
            if not settings.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY is not set")
            self._openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client
