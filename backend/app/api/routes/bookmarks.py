"""Bookmarks: questions the user starred to revisit, kept until unstarred."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.security.rate_limiter import limiter

router = APIRouter(prefix="/bookmarks", tags=["Bookmarks"])


class AddRequest(BaseModel):
    source: str = Field(..., pattern="^(mcq|exam)$")
    subject: str | None = Field(default=None, max_length=50)
    topic: str | None = Field(default=None, max_length=200)
    question: dict = Field(...)


class RemoveRequest(BaseModel):
    front: str = Field(..., min_length=1, max_length=4000)


class BookmarkItem(BaseModel):
    source: str
    subject: str | None
    topic: str | None
    question: dict


@router.post("/", status_code=204)
@limiter.limit("2000/day")
@limiter.limit("120/minute")
async def add_bookmark(
    request: Request,
    body: AddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not str(body.question.get("question", "")).strip():
        return  # nothing to key on — silently ignore malformed payloads
    await crud.add_bookmark(
        db, current_user.id, source=body.source,
        subject=body.subject, topic=body.topic, question=body.question,
    )


@router.get("/", response_model=list[BookmarkItem])
async def list_bookmarks(
    subject: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BookmarkItem]:
    rows = await crud.get_bookmarks(db, current_user.id, subject=subject, limit=limit)
    return [BookmarkItem(source=r.source, subject=r.subject, topic=r.topic, question=r.question) for r in rows]


@router.post("/remove")
async def remove_bookmark(
    body: RemoveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    removed = await crud.remove_bookmark(db, current_user.id, body.front)
    return {"removed": removed}
