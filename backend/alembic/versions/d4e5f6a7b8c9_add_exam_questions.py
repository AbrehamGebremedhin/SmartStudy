"""add_exam_questions

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exam_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("original_subject", sa.String(), nullable=False),
        sa.Column("stream", sa.String(), nullable=True),
        sa.Column("year", sa.String(), nullable=True),
        sa.Column("exam_name", sa.String(), nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("topic", sa.String(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("passage", sa.Text(), nullable=True),
        sa.Column("question_image_url", sa.String(), nullable=True),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct_answer", sa.String(), nullable=True),
        sa.Column("answer_source", sa.String(), nullable=False, server_default="inferred"),
        sa.Column("answer_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("correct_explanations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("incorrect_explanations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("workout_steps", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.String(), nullable=False, server_default="medium"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exam_questions_content_hash"), "exam_questions", ["content_hash"], unique=True)
    op.create_index(op.f("ix_exam_questions_subject"), "exam_questions", ["subject"])
    op.create_index("ix_exam_questions_subject_year", "exam_questions", ["subject", "year"])
    op.create_index("ix_exam_questions_subject_grade_unit", "exam_questions", ["subject", "grade", "unit"])


def downgrade() -> None:
    op.drop_index("ix_exam_questions_subject_grade_unit", table_name="exam_questions")
    op.drop_index("ix_exam_questions_subject_year", table_name="exam_questions")
    op.drop_index(op.f("ix_exam_questions_subject"), table_name="exam_questions")
    op.drop_index(op.f("ix_exam_questions_content_hash"), table_name="exam_questions")
    op.drop_table("exam_questions")
