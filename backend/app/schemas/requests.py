import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.security.input_sanitizer import sanitize

ValidSubject = Literal[
    "biology", "chemistry", "civics", "economics", "english",
    "general_business", "geography", "history", "maths", "physics", "sat",
]

ValidGrade = Annotated[int, Field(ge=9, le=12)]


def _clean(value: str) -> str:
    result = sanitize(value)
    if result.injection_detected:
        raise ValueError("Invalid input detected.")
    return result.cleaned


class MCQRequest(BaseModel):
    subject: ValidSubject
    grade: ValidGrade | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    topic: str | None = Field(default=None, min_length=1, max_length=200)
    note_id: uuid.UUID | None = None
    chat_session_id: uuid.UUID | None = None
    num_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard", "challenging"] = "medium"

    @field_validator("unit", "topic", mode="before")
    @classmethod
    def sanitize_text_fields(cls, v: str | None) -> str | None:
        return _clean(v) if v is not None else v


class FlashcardRequest(BaseModel):
    subject: ValidSubject
    grade: ValidGrade | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    topic: str | None = Field(default=None, min_length=1, max_length=200)
    note_id: uuid.UUID | None = None
    chat_session_id: uuid.UUID | None = None
    num_cards: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard", "challenging"] = "medium"

    @field_validator("unit", "topic", mode="before")
    @classmethod
    def sanitize_text_fields(cls, v: str | None) -> str | None:
        return _clean(v) if v is not None else v


class NotesRequest(BaseModel):
    subject: ValidSubject
    topic: str = Field(min_length=1, max_length=200)
    grade: ValidGrade | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    chat_session_id: uuid.UUID | None = None
    version: str = Field(default="1.0", max_length=10)

    @field_validator("topic", "unit", mode="before")
    @classmethod
    def sanitize_text_fields(cls, v: str | None) -> str | None:
        return _clean(v) if v is not None else v


class NoteChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    chat_history: list[dict] = Field(default_factory=list, max_length=20)

    @field_validator("question", mode="before")
    @classmethod
    def sanitize_question(cls, v: str) -> str:
        return _clean(v)


class ChatSessionCreateRequest(BaseModel):
    subject: ValidSubject
    grade: ValidGrade | None = None
    title: str = Field(default="New Chat", min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        return _clean(v)


class ChatMessageRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question", mode="before")
    @classmethod
    def sanitize_question(cls, v: str) -> str:
        return _clean(v)


class UpdateSessionTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v: str) -> str:
        return _clean(v)


class EvaluateAnswerRequest(BaseModel):
    subject: ValidSubject
    question: dict
    student_answer: str = Field(min_length=1, max_length=5000)
    note: dict | str | None = None

    @field_validator("student_answer", mode="before")
    @classmethod
    def sanitize_answer(cls, v: str) -> str:
        return _clean(v)
