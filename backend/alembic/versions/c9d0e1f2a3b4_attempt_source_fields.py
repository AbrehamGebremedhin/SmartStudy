"""question_attempts source/question_id/score

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All nullable: pre-existing rows are a legacy mcq/exam mix (source NULL).
    op.add_column("question_attempts", sa.Column("source", sa.String(), nullable=True))
    op.add_column("question_attempts", sa.Column("question_id", UUID(as_uuid=True), nullable=True))
    op.add_column("question_attempts", sa.Column("score", sa.Numeric(3, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("question_attempts", "score")
    op.drop_column("question_attempts", "question_id")
    op.drop_column("question_attempts", "source")
