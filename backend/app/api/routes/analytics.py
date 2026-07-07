"""Question-attempt logging + per-unit mastery analytics."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.security.rate_limiter import limiter

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class Attempt(BaseModel):
    subject: str = Field(..., max_length=50)
    grade: int | None = None
    unit: str | None = Field(default=None, max_length=100)
    topic: str | None = Field(default=None, max_length=200)
    correct: bool
    # Clients may only claim the flows they grade deterministically; "review"
    # rows are written server-side by the evaluate route, where the grade is
    # produced. None = legacy clients.
    source: Literal["mcq", "exam", "drill"] | None = None
    question_id: uuid.UUID | None = None  # exam_questions.id when the question has one


class AttemptsRequest(BaseModel):
    attempts: list[Attempt] = Field(..., max_length=200)


class MasteryRow(BaseModel):
    subject: str
    grade: int | None
    unit: str | None
    source: str | None = None  # only populated when by_source=true
    total: int
    correct: int
    accuracy: int


class TrendRow(BaseModel):
    date: str  # YYYY-MM-DD, Africa/Addis_Ababa day boundaries
    source: str | None  # None = legacy rows (pre-source mcq/exam mix)
    total: int
    correct: int


class RetentionRow(BaseModel):
    subject: str
    total: int
    strong: int  # cards in Leitner box 3+


@router.post("/attempts", status_code=204)
@limiter.limit("2000/day")
@limiter.limit("120/minute")
async def record_attempts(
    request: Request,
    body: AttemptsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await crud.record_attempts(db, current_user.id, [a.model_dump() for a in body.attempts])


@router.get("/mastery", response_model=list[MasteryRow])
async def mastery(
    subject: str | None = Query(default=None, max_length=50),
    by_source: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MasteryRow]:
    return [MasteryRow(**r) for r in await crud.get_mastery(db, current_user.id, subject=subject, by_source=by_source)]


@router.get("/trends", response_model=list[TrendRow])
async def trends(
    days: int = Query(default=30, ge=1, le=365),
    subject: str | None = Query(default=None, max_length=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TrendRow]:
    return [TrendRow(**r) for r in await crud.get_trends(db, current_user.id, days=days, subject=subject)]


@router.get("/retention", response_model=list[RetentionRow])
async def retention(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RetentionRow]:
    return [RetentionRow(**r) for r in await crud.get_retention(db, current_user.id)]
