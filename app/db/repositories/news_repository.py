"""뉴스 리포지토리 — DB 쿼리 캡슐화."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import NewsArticleDB, NewsChunkDB

logger = logging.getLogger(__name__)

# pg_trgm word_similarity 임계값
# GIN 인덱스 필요: CREATE INDEX idx_chunks_trgm ON news_chunks USING gin(chunk_text gin_trgm_ops);
_TRGM_THRESHOLD = 0.05


class NewsRepository:
    """news_articles + news_chunks 테이블 쿼리 담당."""

    def __init__(self, session: Session):
        self._session = session

    # -------------------------------------------------------------------------
    # Article 조회
    # -------------------------------------------------------------------------

    def get_articles_by_keyword(
        self,
        query: str,
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[NewsArticleDB]:
        """제목·본문 ILIKE 기사 검색 (분석 엔드포인트용)."""
        pattern = f"%{query}%"
        stmt = (
            select(NewsArticleDB)
            .where(
                NewsArticleDB.title.ilike(pattern)
                | NewsArticleDB.body.ilike(pattern)
            )
        )
        if category_l2:
            stmt = stmt.where(NewsArticleDB.category_l2 == category_l2)
        stmt = stmt.order_by(NewsArticleDB.published_at.desc()).limit(limit)
        return list(self._session.execute(stmt).scalars())

    # -------------------------------------------------------------------------
    # Chunk 조회 (RAG 파이프라인)
    # -------------------------------------------------------------------------

    def search_chunks_by_vector(
        self,
        embedding: list[float],
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[tuple[NewsChunkDB, NewsArticleDB]]:
        """코사인 유사도 벡터 검색 — V1/V2/V3 공통."""
        stmt = (
            select(NewsChunkDB, NewsArticleDB)
            .join(NewsArticleDB, NewsChunkDB.article_id == NewsArticleDB.id)
            .where(NewsChunkDB.embedding.is_not(None))
        )
        if category_l2:
            stmt = stmt.where(NewsArticleDB.category_l2 == category_l2)
        stmt = (
            stmt
            .order_by(NewsChunkDB.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        return [(row[0], row[1]) for row in self._session.execute(stmt)]

    def search_chunks_by_keyword(
        self,
        query: str,
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[tuple[NewsChunkDB, NewsArticleDB]]:
        """pg_trgm word_similarity 키워드 검색 — V2/V3 Hybrid용.

        GIN 인덱스: CREATE INDEX idx_chunks_trgm ON news_chunks
                    USING gin(chunk_text gin_trgm_ops);
        """
        trgm_score = func.word_similarity(query, NewsChunkDB.chunk_text)
        stmt = (
            select(NewsChunkDB, NewsArticleDB)
            .join(NewsArticleDB, NewsChunkDB.article_id == NewsArticleDB.id)
            .where(trgm_score > _TRGM_THRESHOLD)
        )
        if category_l2:
            stmt = stmt.where(NewsArticleDB.category_l2 == category_l2)
        stmt = stmt.order_by(trgm_score.desc()).limit(limit)
        return [(row[0], row[1]) for row in self._session.execute(stmt)]
