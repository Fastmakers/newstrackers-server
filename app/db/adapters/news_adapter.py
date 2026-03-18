"""뉴스 어댑터 — DB Row → Domain Model 변환."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import NewsArticleDB, NewsChunkDB

from app.schemas.data_models import NewsArticle, NewsChunk

# 기자명 추출: "홍길동 매경 디지털뉴스룸 기자(gil@mk.co.kr)" → "홍길동"
_WRITER_RE = re.compile(r"^(\S+)")
# 이메일 포함 여부로 기자 정보 여부 판단
_BYLINE_RE = re.compile(r"\([\w.+-]+@[\w.+-]+\)")

SOURCE_NAME = "매일경제"


def _extract_writer(raw: str | None) -> str | None:
    """source_name 원문에서 기자 이름만 추출."""
    if not raw:
        return None
    m = _WRITER_RE.match(raw.strip())
    return m.group(1) if m else None


def _extract_keywords(raw_metadata: dict | None) -> list[str]:
    """raw_metadata.keyword_list 추출."""
    if not raw_metadata:
        return []
    kw = raw_metadata.get("keyword_list")
    if isinstance(kw, list):
        return [str(k) for k in kw if k]
    return []


def article_row_to_domain(row: "NewsArticleDB") -> NewsArticle:
    """NewsArticleDB ORM → NewsArticle 도메인 모델."""
    return NewsArticle(
        id=row.id,
        title=row.title or "",
        summary=row.summary,
        body=row.body or "",
        source_name=SOURCE_NAME,
        writer=_extract_writer(row.writer or row.source_name),
        article_url=row.article_url,
        category_l1=row.category_l1,
        category_l2=row.category_l2,
        category_l3=row.category_l3,
        published_at=row.published_at,
        keyword_list=_extract_keywords(row.raw_metadata),
    )


def chunk_row_to_domain(
    row: "NewsChunkDB",
    article: NewsArticle | None = None,
    distance: float | None = None,
) -> NewsChunk:
    """NewsChunkDB ORM → NewsChunk 도메인 모델."""
    return NewsChunk(
        id=row.id,
        article_id=row.article_id,
        chunk_no=row.chunk_no or 0,
        chunk_text=row.chunk_text or "",
        chunk_chars=row.chunk_chars or 0,
        article=article,
        distance=distance,
    )
