"""add preprocessing columns

Revision ID: 002
Revises: 001
Create Date: 2026-03-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "news_article_embeddings",
        sa.Column("content_clean", sa.Text(), nullable=True),
    )
    op.add_column(
        "news_article_embeddings",
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "news_article_embeddings",
        sa.Column("log_ttr", sa.Float(), nullable=True),
    )
    op.create_index(
        "idx_embeddings_is_valid", "news_article_embeddings", ["is_valid"]
    )


def downgrade() -> None:
    op.drop_index("idx_embeddings_is_valid", table_name="news_article_embeddings")
    op.drop_column("news_article_embeddings", "log_ttr")
    op.drop_column("news_article_embeddings", "is_valid")
    op.drop_column("news_article_embeddings", "content_clean")
