"""뉴스 리포지토리 — DB 쿼리 캡슐화."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import String, cast, func, literal, select, text
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
    ) -> list[tuple[NewsChunkDB, NewsArticleDB, float]]:
        """코사인 유사도 벡터 검색 — V1/V2/V3 공통.

        HNSW 인덱스 활용을 위해 서브쿼리로 먼저 Top-N을 뽑은 뒤 JOIN.
        (JOIN + ORDER BY 구조에서는 플래너가 HNSW를 Seq Scan으로 대체함)

        Returns: (chunk, article, cosine_distance) 튜플 리스트
        """
        cos_dist = NewsChunkDB.embedding.cosine_distance(embedding)

        # Step 1: HNSW로 Top-N chunk id만 추출 (JOIN 없이)
        inner = (
            select(NewsChunkDB.id)
            .where(NewsChunkDB.embedding.is_not(None))
            .order_by(cos_dist)
            .limit(limit)
        ).subquery()

        # Step 2: 추출된 id로 JOIN + 거리 컬럼 포함
        stmt = (
            select(NewsChunkDB, NewsArticleDB, cos_dist.label("distance"))
            .join(inner, NewsChunkDB.id == inner.c.id)
            .join(NewsArticleDB, NewsChunkDB.article_id == NewsArticleDB.id)
            .where(func.length(NewsChunkDB.chunk_text) >= 100)
        )
        if category_l2:
            stmt = stmt.where(NewsArticleDB.category_l2 == category_l2)
        stmt = stmt.order_by(cos_dist)
        return [(row[0], row[1], float(row[2])) for row in self._session.execute(stmt)]

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
        # GIN 인덱스 활용: <<% 연산자 (word_similarity 함수형 > threshold는 GIN 미사용)
        # title 유사도에 2배 가중치 — 제목에 기업명이 있는 기사를 우선 노출
        chunk_score = func.word_similarity(cast(query, String), NewsChunkDB.chunk_text)
        title_score = func.word_similarity(cast(query, String), NewsArticleDB.title)
        combined_score = title_score * 2 + chunk_score
        stmt = (
            select(NewsChunkDB, NewsArticleDB)
            .join(NewsArticleDB, NewsChunkDB.article_id == NewsArticleDB.id)
            .where(literal(query).op("<<%")(NewsChunkDB.chunk_text))
            .where(func.length(NewsChunkDB.chunk_text) >= 100)
        )
        if category_l2:
            stmt = stmt.where(NewsArticleDB.category_l2 == category_l2)
        stmt = stmt.order_by(combined_score.desc()).limit(limit)
        return [(row[0], row[1]) for row in self._session.execute(stmt)]
