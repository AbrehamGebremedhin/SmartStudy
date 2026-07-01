"""Question-attempt logging + per-unit mastery analytics."""

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


class AttemptsRequest(BaseModel):
    attempts: list[Attempt] = Field(..., max_length=200)


class MasteryRow(BaseModel):
    subject: str
    grade: int | None
    unit: str | None
    total: int
    correct: int
    accuracy: int


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MasteryRow]:
    return [MasteryRow(**r) for r in await crud.get_mastery(db, current_user.id, subject=subject)]
