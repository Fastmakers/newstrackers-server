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
from app.services.search.rrf import rrf_fuse, rrf_fuse_multi

logger = logging.getLogger(__name__)

# V3: Cross-Encoder에 전달할 RRF 후보 수
_V3_RERANK_POOL = 40


class NewsService:
    """뉴스 검색 서비스 — 읽기 전용."""

    def __init__(self, session_factory=None, embedding_service=None):
        self._session_factory = session_factory
        self._embedding_service = embedding_service  # Injected or lazy-init
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

    # 토픽 다양성 필터에서 제외할 공통어 (회사명·일반 명사)
    _TOPIC_SKIP: frozenset[str] = frozenset([
        "롯데면세점", "롯데", "면세점", "면세", "한국", "국내", "업계", "관련",
    ])

    @staticmethod
    def _title_roots(title: str) -> set[str]:
        """제목에서 의미 있는 토큰의 앞 3글자(한국어 어근 근사)를 추출."""
        # 직선·곡선 따옴표, 말줄임표, 괄호류, 구두점 제거
        _PUNCT = '…\u201c\u201d\u2018\u2019"\'""\'\'.,!?·[]()【】「」『』'
        roots: set[str] = set()
        for token in title.split():
            token = token.strip(_PUNCT)
            if len(token) >= 3 and token not in NewsService._TOPIC_SKIP:
                roots.add(token[:3])
        return roots

    @staticmethod
    def _dedup(chunks: list[NewsChunk], top_k: int, topic_diversity: bool = False) -> list[NewsChunk]:
        """article_id 기준 중복 청크 제거.

        topic_diversity=True 시 같은 토픽(제목 어근 3글자 기준) 기사를
        최대 2개로 제한해 특정 이슈 독점을 방지.
        """
        seen: set[int] = set()
        result: list[NewsChunk] = []
        root_counts: dict[str, int] = {}  # 어근 → 선택된 기사 수 (다양성용)

        for chunk in chunks:
            if chunk.article_id in seen:
                continue

            if topic_diversity:
                title = chunk.article.title if chunk.article else ""
                roots = NewsService._title_roots(title)
                # 이미 2개 이상의 기사에서 등장한 어근이 있으면 같은 토픽 → 스킵
                if any(root_counts.get(r, 0) >= 2 for r in roots):
                    continue
                for r in roots:
                    root_counts[r] = root_counts.get(r, 0) + 1

            seen.add(chunk.article_id)
            result.append(chunk)
            if len(result) == top_k:
                break

        return result

    @staticmethod
    def _title_boost(chunks: list[NewsChunk], company: str) -> list[NewsChunk]:
        """제목·카테고리에 기업명 포함 시 RRF 점수에 보너스 — V1/V2 경량 재정렬.

        base_score = 1 / (60 + rank)  (RRF 방식)
        bonus      = 0.3 if company in title
        최종 정렬 : base_score + bonus 내림차순
        """
        scored = []
        for rank, chunk in enumerate(chunks, start=1):
            title = chunk.article.title if chunk.article else ""
            bonus = 0.3 if company and company in title else 0.0
            scored.append((1.0 / (60 + rank) + bonus, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def vector_search(
        self,
        query: str,
        company: str = "",
        category_l2: Optional[str] = None,
        top_k: int = 5,
    ) -> list[NewsChunk]:
        """V1 Baseline — 벡터 유사도 검색 + title 기업명 보너스 재정렬.

        Args:
            query:       자소서 원문 (임베딩 후 코사인 유사도 검색)
            company:     기업명 (title 보너스용)
            category_l2: 카테고리 필터
            top_k:       반환 청크 수
        """
        embedding = self.embed_query(query)
        chunks = self._vector_search_chunks(embedding, category_l2, limit=100)
        if company:
            chunks = self._title_boost(chunks, company)
        return self._dedup(chunks, top_k)

    def hybrid_search(
        self,
        query: str,
        keyword_query: Optional[str] = None,
        category_l2: Optional[str] = None,
        top_k: int = 5,
    ) -> list[NewsChunk]:
        """V2 — 하이브리드 검색 (벡터 + pg_trgm → RRF → Top K).

        병렬 처리:
            embed_query ──────────────► vector_search ─┐
            keyword_search (pg_trgm) ──────────────────┤► RRF ► Top K

        Args:
            query:         Haiku가 변환한 압축 쿼리 (벡터 임베딩용)
            keyword_query: pg_trgm 검색용 쿼리 (기본값: query와 동일)
                           기업명만 넣으면 더 정밀한 keyword 매칭 가능
            top_k:         최종 반환 청크 수
        """
        kw_query = keyword_query or query
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_embed = executor.submit(self.embed_query, query)
            future_keyword = executor.submit(self._keyword_search_chunks, kw_query, category_l2)

            embedding = future_embed.result()
            future_vector = executor.submit(self._vector_search_chunks, embedding, category_l2)

            keyword_chunks = future_keyword.result()
            vector_chunks = future_vector.result()

        fused = rrf_fuse(vector_chunks, keyword_chunks, top_n=100)
        return self._dedup(fused, top_k)

    def multi_hybrid_search(
        self,
        queries: list[str],
        keyword_query: str = "",
        category_l2: Optional[str] = None,
        top_k: int = 15,
    ) -> list[NewsChunk]:
        """멀티쿼리 하이브리드 검색 — 각 쿼리 hybrid_search 병렬 실행 후 RRF 합산.

        Args:
            queries:       transform_query가 생성한 검색 쿼리 리스트
            keyword_query: pg_trgm 키워드 검색용 (보통 기업명)
            top_k:         최종 반환 청크 수
        """
        if not queries:
            return []

        with ThreadPoolExecutor(max_workers=len(queries)) as executor:
            futures = [
                executor.submit(self.hybrid_search, q, keyword_query, category_l2, top_k * 3)
                for q in queries
            ]
            result_lists = [f.result() for f in futures]

        fused = rrf_fuse_multi(result_lists, top_n=100)
        return self._dedup(fused, top_k, topic_diversity=True)

    def rerank_chunks(
        self,
        query: str,
        chunks: list[NewsChunk],
        top_k: int = 5,
    ) -> list[NewsChunk]:
        """V3 — Cross-Encoder 재배열 (hybrid_search 결과를 입력으로 받음).

        Args:
            query:  검색 쿼리 (Cross-Encoder 스코어링 기준)
            chunks: hybrid_search가 반환한 후보 청크 (최대 _V3_RERANK_POOL개 권장)
            top_k:  최종 반환 청크 수
        """
        reranked = self._get_reranker().rerank(query, chunks, top_n=len(chunks))
        return self._dedup(reranked, top_k)

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
        """쿼리 텍스트 → OpenAI 임베딩 벡터 (EmbeddingService 위임)."""
        if self._embedding_service is None:
            from app.services.embedding_service import EmbeddingService
            self._embedding_service = EmbeddingService()
        return self._embedding_service.embed_query(text)

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
        """코사인 유사도 벡터 검색 (distance 포함)."""
        try:
            with self._repo() as db:
                rows = NewsRepository(db).search_chunks_by_vector(
                    embedding, category_l2, limit=limit
                )
                return [chunk_row_to_domain(c, article_row_to_domain(a), distance=d) for c, a, d in rows]
        except Exception as e:
            logger.error("벡터 검색 오류: %s", e)
            return []

    def _get_reranker(self):
        """Cross-Encoder 리랭커 — 첫 호출 시 lazy-load."""
        if self._reranker is None:
            from app.services.search.reranker import CrossEncoderReranker
            self._reranker = CrossEncoderReranker()
        return self._reranker
