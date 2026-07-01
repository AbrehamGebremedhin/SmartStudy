"""Mistake bank: wrong-answered questions, re-served until the user gets them right."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.security.rate_limiter import limiter

router = APIRouter(prefix="/mistakes", tags=["Mistakes"])


class RecordRequest(BaseModel):
    source: str = Field(..., pattern="^(mcq|exam)$")
    subject: str | None = Field(default=None, max_length=50)
    topic: str | None = Field(default=None, max_length=200)
    # Full question snapshot (opaque to the backend; the review UI owns its shape).
    # Must carry a "question" string — that's the dedup key.
    question: dict = Field(...)


class ResolveRequest(BaseModel):
    front: str = Field(..., min_length=1, max_length=4000)


class MistakeItem(BaseModel):
    source: str
    subject: str | None
    topic: str | None
    question: dict


@router.post("/", status_code=204)
@limiter.limit("2000/day")
@limiter.limit("120/minute")
async def record_mistake(
    request: Request,
    body: RecordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not str(body.question.get("question", "")).strip():
        return  # nothing to key on — silently ignore malformed payloads
    await crud.record_mistake(
        db, current_user.id, source=body.source,
        subject=body.subject, topic=body.topic, question=body.question,
    )


@router.get("/", response_model=list[MistakeItem])
async def list_mistakes(
    subject: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MistakeItem]:
    rows = await crud.get_mistakes(db, current_user.id, subject=subject, limit=limit)
    return [MistakeItem(source=r.source, subject=r.subject, topic=r.topic, question=r.question) for r in rows]


@router.get("/count")
async def mistakes_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"count": await crud.count_mistakes(db, current_user.id)}


@router.post("/resolve")
async def resolve_mistake(
    body: ResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    removed = await crud.resolve_mistake(db, current_user.id, body.front)
    return {"resolved": removed}
