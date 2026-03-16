"""replace analysis_jobs status/created_at indexes with composite index

- idx_jobs_status, idx_jobs_created_at 개별 인덱스 제거
- idx_jobs_status_created_at (status, created_at) 복합 인덱스 추가

이유:
  claim_pending_jobs()의 쿼리 패턴이
    WHERE status = 'pending' ORDER BY created_at ASC LIMIT n FOR UPDATE SKIP LOCKED
  이므로 복합 인덱스가 필터 + 정렬을 단일 인덱스 스캔으로 처리한다.
  개별 인덱스 두 개를 사용하면 status 인덱스 필터 후 별도 sort 단계가 발생한다.

Revision ID: 006
Revises: 005
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_jobs_status", table_name="analysis_jobs")
    op.drop_index("idx_jobs_created_at", table_name="analysis_jobs")
    op.create_index(
        "idx_jobs_status_created_at",
        "analysis_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_status_created_at", table_name="analysis_jobs")
    op.create_index("idx_jobs_status", "analysis_jobs", ["status"])
    op.create_index("idx_jobs_created_at", "analysis_jobs", ["created_at"])
