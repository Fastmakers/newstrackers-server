"""add analysis_jobs and analysis_reports tables

Revision ID: 004
Revises: 003
Create Date: 2026-03-12

비동기 분석 처리를 위한 Job 스케줄 테이블과 결과 저장 테이블 추가.
users 테이블(003)이 먼저 생성된 후 실행된다.
user_id는 users.id를 참조하지만 FK 제약은 걸지 않는다
(분석 기록이 사용자 삭제에 연쇄 삭제되지 않도록 의도적 설계).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # analysis_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "analysis_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        # 입력 파라미터
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("career_level", sa.Text(), nullable=False, server_default="신입"),
        sa.Column("resume_text", sa.Text(), nullable=True),
        # 진행 상황
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("step_label", sa.Text(), nullable=True),
        sa.Column("step_detail", sa.Text(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        # 타임스탬프
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
    )
    op.create_index("idx_jobs_user_id", "analysis_jobs", ["user_id"])
    op.create_index("idx_jobs_status", "analysis_jobs", ["status"])
    op.create_index("idx_jobs_created_at", "analysis_jobs", ["created_at"])

    # ------------------------------------------------------------------
    # analysis_reports
    # ------------------------------------------------------------------
    op.create_table(
        "analysis_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        # ReportResponse 필드 (JSONB / TEXT)
        sa.Column("resume_profile", JSONB, nullable=True),
        sa.Column("matched_news", JSONB, nullable=True),
        sa.Column("matched_news_count", sa.Integer(), nullable=True),
        sa.Column("relevance_analysis", sa.Text(), nullable=True),
        sa.Column("swot", JSONB, nullable=True),
        sa.Column("final_report", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_reports_user_id", "analysis_reports", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_reports_user_id", table_name="analysis_reports")
    op.drop_table("analysis_reports")

    op.drop_index("idx_jobs_created_at", table_name="analysis_jobs")
    op.drop_index("idx_jobs_status", table_name="analysis_jobs")
    op.drop_index("idx_jobs_user_id", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
