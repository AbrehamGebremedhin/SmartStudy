"""add flashcard_reviews table (spaced repetition)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "flashcard_reviews",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("card_key", sa.String(length=64), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("box", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_rated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "card_key"),
    )
    op.create_index("ix_flashcard_reviews_user_due", "flashcard_reviews", ["user_id", "due_at"])
    op.create_index("ix_flashcard_reviews_subject", "flashcard_reviews", ["subject"])


def downgrade() -> None:
    op.drop_index("ix_flashcard_reviews_subject", table_name="flashcard_reviews")
    op.drop_index("ix_flashcard_reviews_user_due", table_name="flashcard_reviews")
    op.drop_table("flashcard_reviews")
