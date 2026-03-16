from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

EMBEDDING_DIM = 1536


class NewsArticleDB(Base):
    """매일경제 원문 기사 테이블 (news_articles)."""

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_article_id: Mapped[Optional[str]] = mapped_column(Text)
    source_name: Mapped[Optional[str]] = mapped_column(Text)   # 기자명+이메일 원문
    title: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    body: Mapped[Optional[str]] = mapped_column(Text)
    article_url: Mapped[Optional[str]] = mapped_column(Text)
    category_l1: Mapped[Optional[str]] = mapped_column(Text)
    category_l2: Mapped[Optional[str]] = mapped_column(Text)
    category_l3: Mapped[Optional[str]] = mapped_column(Text)
    writer: Mapped[Optional[str]] = mapped_column(Text)
    lang: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    content_hash: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    chunks: Mapped[list["NewsChunkDB"]] = relationship(
        "NewsChunkDB", back_populates="article", lazy="noload"
    )

    __table_args__ = (
        Index("idx_articles_category_l2", "category_l2"),
        Index("idx_articles_published_at", "published_at"),
        Index("idx_articles_content_hash", "content_hash"),
    )


class NewsChunkDB(Base):
    """청킹 + 임베딩 완료 테이블 (news_chunks).

    chunk_version = v1_1000_180: 1000자 청크, 180자 오버랩
    section_type  = body (전부 본문)
    embedding_model = text-embedding-3-small
    """

    __tablename__ = "news_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    article_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("news_articles.id"), index=True)
    chunk_version: Mapped[Optional[str]] = mapped_column(Text)
    chunk_no: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_text: Mapped[Optional[str]] = mapped_column(Text)
    chunk_chars: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_tokens_est: Mapped[Optional[int]] = mapped_column(Integer)
    section_type: Mapped[Optional[str]] = mapped_column(Text)
    embedding_model: Mapped[Optional[str]] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    article: Mapped["NewsArticleDB"] = relationship(
        "NewsArticleDB", back_populates="chunks", lazy="noload"
    )

    __table_args__ = (
        Index("idx_chunks_article_id", "article_id"),
    )


# 하위 호환: 기존 코드가 NewsArticle 이름으로 import하던 것 유지
NewsArticle = NewsArticleDB


class AnalysisJobDB(Base):
    """비동기 분석 Job 스케줄 테이블 (analysis_jobs)."""

    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")

    # 입력 파라미터
    company: Mapped[Optional[str]] = mapped_column(Text)
    job_title: Mapped[Optional[str]] = mapped_column(Text)
    industry: Mapped[Optional[str]] = mapped_column(Text)
    career_level: Mapped[str] = mapped_column(Text, default="신입")
    resume_text: Mapped[Optional[str]] = mapped_column(Text)

    # 진행 상황
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    report_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_reports.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_msg: Mapped[Optional[str]] = mapped_column(Text)

    report: Mapped[Optional["AnalysisReportDB"]] = relationship(
        "AnalysisReportDB", foreign_keys=[report_id], lazy="noload"
    )

    __table_args__ = (
        Index("idx_jobs_user_id", "user_id"),
        # claim_pending_jobs 쿼리: WHERE status='pending' ORDER BY created_at
        # 복합 인덱스로 필터 + 정렬을 단일 스캔에 처리 (FOR UPDATE SKIP LOCKED 성능)
        Index("idx_jobs_status_created_at", "status", "created_at"),
    )


class AnalysisReportDB(Base):
    """분석 완료 리포트 저장 테이블 (analysis_reports)."""

    __tablename__ = "analysis_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ReportResponse 필드
    resume_profile: Mapped[Optional[dict]] = mapped_column(JSONB)
    matched_news: Mapped[Optional[list]] = mapped_column(JSONB)
    matched_news_count: Mapped[Optional[int]] = mapped_column(Integer)
    relevance_analysis: Mapped[Optional[str]] = mapped_column(Text)
    swot: Mapped[Optional[dict]] = mapped_column(JSONB)
    final_report: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


    __table_args__ = (
        Index("idx_reports_user_id", "user_id"),
    )
