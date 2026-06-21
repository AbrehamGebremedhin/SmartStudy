"""exam_questions validation fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-21

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("exam_questions", sa.Column("validation_score", sa.Integer(), nullable=True))
    op.add_column("exam_questions", sa.Column("answer_agreed", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("exam_questions", "answer_agreed")
    op.drop_column("exam_questions", "validation_score")
