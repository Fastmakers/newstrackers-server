"""임베딩 서비스 — OpenAI text-embedding-3-small."""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingService:
    """OpenAI 임베딩 서비스 — 쿼리 텍스트를 벡터로 변환."""

    def __init__(self, api_key: str = None):
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._client = None  # Lazy-init

    @property
    def _openai(self):
        if self._client is None:
            if not self._api_key:
                raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def embed_query(self, text: str) -> list[float]:
        """텍스트 → 임베딩 벡터 (text-embedding-3-small)."""
        response = self._openai.embeddings.create(model=EMBEDDING_MODEL, input=text)
        return response.data[0].embedding
