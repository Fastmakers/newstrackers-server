"""create news_articles table

Revision ID: 001
Revises:
Create Date: 2026-02-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("content", sa.Text()),
        sa.Column("url", sa.Text(), unique=True, nullable=False),
        sa.Column("image_url", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(255)),
        sa.Column("author", sa.String(255)),
        sa.Column("query", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_articles_query", "news_articles", ["query"])
    op.create_index("idx_articles_published_at", "news_articles", ["published_at"])


def downgrade() -> None:
    op.drop_index("idx_articles_published_at")
    op.drop_index("idx_articles_query")
    op.drop_table("news_articles")
