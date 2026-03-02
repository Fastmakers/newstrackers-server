import asyncpg
from openai import AsyncOpenAI
from pgvector.asyncpg import register_vector

from app.core.config import settings

EMBEDDING_DIM = 1536
EMBEDDING_MODEL = "text-embedding-3-small"


class VectorStoreService:
    """pgvector 기반 Vector Store 서비스 (news_chunks/news_articles 테이블 사용)"""

    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        self._openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def init_db(self):
        """커넥션 풀 생성"""
        self._pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=2,
            max_size=10,
            init=register_vector,
        )

    async def close(self):
        """커넥션 풀 종료"""
        if self._pool:
            await self._pool.close()

    async def _embed(self, text: str) -> list[float]:
        """OpenAI text-embedding-3-small으로 임베딩 생성 (1536차원)"""
        response = await self._openai.embeddings.create(
            input=text,
            model=EMBEDDING_MODEL,
        )
        return response.data[0].embedding

    async def search(
        self,
        query: str,
        job_category: str | None = None,
        n_results: int = 10,
    ) -> list[dict]:
        """코사인 유사도 기반 뉴스 검색 (news_chunks + news_articles 조인)"""
        query_embedding = await self._embed(query)

        async with self._pool.acquire() as conn:
            if job_category:
                sql = """
                    SELECT
                        nc.id AS chunk_id,
                        nc.chunk_text,
                        na.id AS article_id,
                        na.title,
                        na.article_url,
                        na.category_l1,
                        na.category_l2,
                        na.category_l3,
                        na.published_at,
                        nc.embedding <=> $1::vector AS distance
                    FROM news_chunks nc
                    JOIN news_articles na ON na.id = nc.article_id
                    WHERE
                        na.category_l1 ILIKE $2
                        OR na.category_l2 ILIKE $2
                        OR na.category_l3 ILIKE $2
                    ORDER BY distance
                    LIMIT $3
                """
                rows = await conn.fetch(sql, query_embedding, f"%{job_category}%", n_results)
            else:
                sql = """
                    SELECT
                        nc.id AS chunk_id,
                        nc.chunk_text,
                        na.id AS article_id,
                        na.title,
                        na.article_url,
                        na.category_l1,
                        na.category_l2,
                        na.category_l3,
                        na.published_at,
                        nc.embedding <=> $1::vector AS distance
                    FROM news_chunks nc
                    JOIN news_articles na ON na.id = nc.article_id
                    ORDER BY distance
                    LIMIT $2
                """
                rows = await conn.fetch(sql, query_embedding, n_results)

        return [
            {
                "id": str(row["chunk_id"]),
                "article_id": str(row["article_id"]),
                "document": row["chunk_text"],
                "metadata": {
                    "title": row["title"],
                    "url": row["article_url"],
                    "job_category": row["category_l1"] or row["category_l2"] or row["category_l3"],
                    "category_l1": row["category_l1"],
                    "category_l2": row["category_l2"],
                    "category_l3": row["category_l3"],
                    "published_at": row["published_at"],
                },
                "distance": float(row["distance"]),
            }
            for row in rows
        ]

    async def get_stats(self) -> dict:
        """Vector DB 통계 정보"""
        async with self._pool.acquire() as conn:
            article_count = await conn.fetchval("SELECT count(*) FROM news_articles")
            chunk_count = await conn.fetchval("SELECT count(*) FROM news_chunks")
        return {
            "total_articles": article_count,
            "total_chunks": chunk_count,
        }


# 싱글톤 인스턴스
vector_store_service = VectorStoreService()
