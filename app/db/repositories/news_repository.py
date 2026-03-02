"""
뉴스 리포지토리 — DB 쿼리 캡슐화.

SPEC: docs/SPEC_SEARCH.md §4, §7
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import NewsArticleDB, NewsChunkDB

logger = logging.getLogger(__name__)

# pg_trgm word_similarity 임계값 (0.0 = 임계 없음, ORDER BY로만 정렬)
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
        """제목·본문 ILIKE 검색 (BM25 교체 예정).

        SPEC §4-1 키워드 검색
        """
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

    def get_articles_by_ids(self, ids: list[int]) -> list[NewsArticleDB]:
        """ID 목록으로 기사 일괄 조회."""
        if not ids:
            return []
        stmt = select(NewsArticleDB).where(NewsArticleDB.id.in_(ids))
        return list(self._session.execute(stmt).scalars())

    def count_articles(self) -> int:
        return self._session.execute(
            text("SELECT COUNT(*) FROM news_articles")
        ).scalar_one()

    # -------------------------------------------------------------------------
    # Chunk 조회
    # -------------------------------------------------------------------------

    def search_chunks_by_vector(
        self,
        embedding: list[float],
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[tuple[NewsChunkDB, NewsArticleDB]]:
        """코사인 유사도 벡터 검색 (SPEC §4-1).

        Returns: list of (chunk, article) tuples
        """
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
        """청크 텍스트 pg_trgm word_similarity 검색 (ILIKE 대체).

        SPEC §4-1 키워드 검색 (chunk 레벨)
        GIN 인덱스: CREATE INDEX idx_chunks_trgm ON news_chunks
                    USING gin(chunk_text gin_trgm_ops);
        Returns: list of (chunk, article) tuples, word_similarity 내림차순
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

    def search_chunks_by_keyword_ilike(
        self,
        query: str,
        category_l2: Optional[str] = None,
        limit: int = 100,
    ) -> list[tuple[NewsChunkDB, NewsArticleDB]]:
        """청크 텍스트 ILIKE 검색 — 베이스라인 비교용.

        benchmark_search.py 에서 pg_trgm 대비 성능 비교에 사용.
        """
        pattern = f"%{query}%"
        stmt = (
            select(NewsChunkDB, NewsArticleDB)
            .join(NewsArticleDB, NewsChunkDB.article_id == NewsArticleDB.id)
            .where(NewsChunkDB.chunk_text.ilike(pattern))
        )
        if category_l2:
            stmt = stmt.where(NewsArticleDB.category_l2 == category_l2)

        stmt = stmt.order_by(NewsArticleDB.published_at.desc()).limit(limit)
        return [(row[0], row[1]) for row in self._session.execute(stmt)]

    def get_chunks_by_article_ids(
        self, article_ids: list[int]
    ) -> list[NewsChunkDB]:
        """기사 ID 목록에 속한 청크 조회."""
        if not article_ids:
            return []
        stmt = (
            select(NewsChunkDB)
            .where(NewsChunkDB.article_id.in_(article_ids))
            .order_by(NewsChunkDB.article_id, NewsChunkDB.chunk_no)
        )
        return list(self._session.execute(stmt).scalars())
