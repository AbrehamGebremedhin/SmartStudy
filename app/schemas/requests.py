from typing import Literal

from pydantic import BaseModel, Field


class MCQRequest(BaseModel):
    subject: str
    grade: int | None = None
    unit: str | None = None
    num_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard", "challenging"] = "medium"


class FlashcardRequest(BaseModel):
    subject: str
    grade: int | None = None
    unit: str | None = None
    topic: str | None = None
    num_cards: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard", "challenging"] = "medium"


class NotesRequest(BaseModel):
    subject: str
    topic: str
    grade: int | None = None
    unit: str | None = None
    version: str = "1.0"


class ChatSessionCreateRequest(BaseModel):
    subject: str
    grade: int | None = None
    title: str = "New Chat"


class ChatMessageRequest(BaseModel):
    question: str


class UpdateSessionTitleRequest(BaseModel):
    title: str


class EvaluateAnswerRequest(BaseModel):
    subject: str
    question: dict
    student_answer: str
    note: str | None = None
