import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.database import Base


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class GenerationType(str, Enum):
    mcq = "mcq"
    flashcard = "flashcard"
    notes = "notes"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


class AnswerSource(str, Enum):
    official = "official"   # correct answer came from the scraped site API
    inferred = "inferred"   # correct answer was solved by the enrichment LLM


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    generations: Mapped[list["UserGeneration"]] = relationship(back_populates="user")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")


class Generation(Base):
    __tablename__ = "generations"
    __table_args__ = (
        Index("ix_generations_type_request_hash", "type", "request_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    request_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user_generations: Mapped[list["UserGeneration"]] = relationship(back_populates="generation")


class UserGeneration(Base):
    __tablename__ = "user_generations"
    __table_args__ = (
        Index("ix_user_generations_user_accessed", "user_id", "accessed_at"),
        Index("ix_user_generations_generation_id", "generation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("generations.id"), nullable=False)
    was_cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="generations")
    generation: Mapped["Generation"] = relationship(back_populates="user_generations")


class ExamQuestion(Base):
    """A past-exam (EUEE/model/Tigray) question, enriched into MCQ-compatible form.

    Populated offline by the enrichment pipeline (scraped data + Milvus topic/grade/
    unit resolution + Gemini explanations/answer-solving). Served by the dedicated
    "Past Exams" practice mode, separate from AI-generated MCQs in `generations`.
    """

    __tablename__ = "exam_questions"
    __table_args__ = (
        Index("ix_exam_questions_subject_year", "subject", "year"),
        Index("ix_exam_questions_subject_grade_unit", "subject", "grade", "unit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Idempotency: stable hash of the source question so the enrichment job can
    # skip/upsert already-processed items and dedup Tigray/model-exam overlaps.
    content_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)

    # Provenance (from the scrape)
    subject: Mapped[str] = mapped_column(String, nullable=False, index=True)   # canonical: maths, sat, biology…
    original_subject: Mapped[str] = mapped_column(String, nullable=False)      # raw scraped label
    stream: Mapped[str | None] = mapped_column(String, nullable=True)          # natural | social | model
    year: Mapped[str | None] = mapped_column(String, nullable=True)            # E.C year, "" for model exams
    exam_name: Mapped[str | None] = mapped_column(String, nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)         # original question number

    # Curriculum placement (resolved via Milvus; null for sat/english)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    topic: Mapped[str | None] = mapped_column(String, nullable=True)

    # Question body
    question: Mapped[str] = mapped_column(Text, nullable=False)
    passage: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Options: list of {"letter": "A", "text": str|null, "image_url": str|null}; 2–5 entries.
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Answer + enrichment
    correct_answer: Mapped[str | None] = mapped_column(String, nullable=True)  # letter A–E
    answer_source: Mapped[str] = mapped_column(String, nullable=False, default=AnswerSource.inferred.value)
    answer_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    correct_explanations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    incorrect_explanations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    workout_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String, nullable=False, default="medium")

    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("ix_chat_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="New Chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", order_by="ChatMessage.timestamp")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    key_concepts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
