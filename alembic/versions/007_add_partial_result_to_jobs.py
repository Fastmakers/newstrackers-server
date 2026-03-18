"""add partial_result JSONB column to analysis_jobs

단계별 완료된 결과를 폴링으로 제공하기 위해 partial_result 컬럼 추가.
Worker가 각 단계 완료 후 이 컬럼을 업데이트하고,
클라이언트는 GET /jobs/{id} 폴링으로 점진적 결과를 렌더링한다.

Revision ID: 007
Revises: 006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_jobs",
        sa.Column("partial_result", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("analysis_jobs", "partial_result")
