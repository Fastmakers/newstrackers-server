"""refactor: job-report 관계 역전, retry 추가, step 컬럼 제거

- analysis_reports: job_id 컬럼 제거 (job이 report를 참조하는 방향으로 변경)
- analysis_jobs: report_id FK 추가, retry_count 추가
- analysis_jobs: current_step, step_label, step_detail 제거 (SSE 제거)

Revision ID: 005
Revises: 004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. analysis_jobs: step 컬럼 제거
    op.drop_column("analysis_jobs", "current_step")
    op.drop_column("analysis_jobs", "step_label")
    op.drop_column("analysis_jobs", "step_detail")

    # 2. analysis_jobs: report_id, retry_count 추가
    op.add_column(
        "analysis_jobs",
        sa.Column("report_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_jobs_report_id",
        "analysis_jobs",
        "analysis_reports",
        ["report_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. analysis_reports: job_id 제거 (FK, unique 제약 먼저 drop)
    op.drop_constraint("analysis_reports_job_id_fkey", "analysis_reports", type_="foreignkey")
    op.drop_constraint("analysis_reports_job_id_key", "analysis_reports", type_="unique")
    op.drop_column("analysis_reports", "job_id")


def downgrade() -> None:
    # report_id 복원
    op.add_column(
        "analysis_reports",
        sa.Column("job_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint("analysis_reports_job_id_key", "analysis_reports", ["job_id"])
    op.create_foreign_key(
        "analysis_reports_job_id_fkey",
        "analysis_reports",
        "analysis_jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("fk_jobs_report_id", "analysis_jobs", type_="foreignkey")
    op.drop_column("analysis_jobs", "report_id")
    op.drop_column("analysis_jobs", "retry_count")

    op.add_column("analysis_jobs", sa.Column("current_step", sa.Integer(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("step_label", sa.Text(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("step_detail", sa.Text(), nullable=True))
