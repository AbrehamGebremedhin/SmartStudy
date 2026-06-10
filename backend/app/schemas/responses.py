import uuid
from datetime import datetime

from pydantic import BaseModel


class MCQResponse(BaseModel):
    generation_id: uuid.UUID
    was_cache_hit: bool
    questions: list[dict]
    difficulty: str
    token_usage: str | None = None


class FlashcardResponse(BaseModel):
    generation_id: uuid.UUID
    was_cache_hit: bool
    flashcards: list[dict]
    difficulty: str
    token_usage: str | None = None


class NotesResponse(BaseModel):
    generation_id: uuid.UUID
    was_cache_hit: bool
    notes: dict
    token_usage: str | None = None


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    subject: str
    grade: int | None
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    key_concepts: list[str]
    timestamp: datetime

    model_config = {"from_attributes": True}


class ChatSessionDetailResponse(BaseModel):
    id: uuid.UUID
    subject: str
    grade: int | None
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageResponse]

    model_config = {"from_attributes": True}


class ChatReplyResponse(BaseModel):
    session_id: uuid.UUID
    title: str
    current_response: dict
    token_usage: str | None = None


class HistoryItemResponse(BaseModel):
    user_generation_id: uuid.UUID
    generation_id: uuid.UUID
    type: str
    request_params: dict
    was_cache_hit: bool
    accessed_at: datetime


class NoteChatResponse(BaseModel):
    answer: str
    key_concepts: list[str]
    follow_up_questions: list[str]
    token_usage: str | None = None


class EvaluateAnswerResponse(BaseModel):
    is_correct: bool
    score: float
    feedback: str
    improvement_suggestions: list[str]
    correct_solution: list[str]
    misconceptions: list[str]
    key_points_missed: list[str]
    strengths: list[str]
    token_usage: str | None = None
