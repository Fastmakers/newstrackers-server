import asyncpg
from openai import AsyncOpenAI
from pgvector.asyncpg import register_vector

from app.core.config import settings

EMBEDDING_DIM = 1536
EMBEDDING_MODEL = "text-embedding-3-small"


class VectorStoreService:
    """pgvector 기반 Vector Store 서비스 (news_article_embeddings 테이블 사용)"""

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
        """코사인 유사도 기반 뉴스 검색 (news_article_embeddings 테이블)"""
        query_embedding = await self._embed(query)

        sql = """
            SELECT id, content, doc_title, doc_source, doc_published, doc_class_code,
                   embedding <=> $1::vector AS distance
            FROM news_article_embeddings
            ORDER BY distance
            LIMIT $2
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, query_embedding, n_results)

        return [
            {
                "id": str(row["id"]),
                "document": row["content"],
                "metadata": {
                    "title": row["doc_title"],
                    "url": row["doc_source"],
                    "job_category": row["doc_class_code"],
                    "published_at": row["doc_published"],
                },
                "distance": float(row["distance"]),
            }
            for row in rows
        ]

    async def get_stats(self) -> dict:
        """Vector DB 통계 정보"""
        async with self._pool.acquire() as conn:
            count = await conn.fetchval("SELECT count(*) FROM news_article_embeddings")
        return {
            "total_documents": count,
        }


# 싱글톤 인스턴스
vector_store_service = VectorStoreService()
