"""add_perf_indexes

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cache lookups filter on both type and request_hash together — single-column
    # indexes were used independently, causing slower lookups.
    op.create_index(
        "ix_generations_type_request_hash",
        "generations",
        ["type", "request_hash"],
    )

    # History queries filter by user_id and sort by accessed_at DESC.
    op.create_index(
        "ix_user_generations_user_accessed",
        "user_generations",
        ["user_id", "accessed_at"],
    )

    # generation_id is an unindexed FK used in JOINs in get_generation_for_user.
    op.create_index(
        "ix_user_generations_generation_id",
        "user_generations",
        ["generation_id"],
    )

    # Active-session queries filter on (user_id, expires_at > now()) and sort by updated_at.
    op.create_index(
        "ix_chat_sessions_user_expires",
        "chat_sessions",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_user_expires", table_name="chat_sessions")
    op.drop_index("ix_user_generations_generation_id", table_name="user_generations")
    op.drop_index("ix_user_generations_user_accessed", table_name="user_generations")
    op.drop_index("ix_generations_type_request_hash", table_name="generations")
