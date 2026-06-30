import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User

router = APIRouter(prefix="/progress", tags=["Progress"])


class ProgressPayload(BaseModel):
    # Opaque gamification blob owned by the frontend; capped at ~64 KB serialized
    # so a client can't store unbounded data under its own user id.
    profile: dict

    @field_validator("profile")
    @classmethod
    def _cap_size(cls, v: dict) -> dict:
        if len(json.dumps(v)) > 64_000:
            raise ValueError("profile too large")
        return v


class ProgressResponse(BaseModel):
    profile: dict | None
    updated_at: datetime | None


@router.get("", response_model=ProgressResponse)
async def get_progress(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    row = await crud.get_user_progress(db, current_user.id)
    if row is None:
        return ProgressResponse(profile=None, updated_at=None)
    return ProgressResponse(profile=row.profile, updated_at=row.updated_at)


@router.put("", response_model=ProgressResponse)
async def put_progress(
    payload: ProgressPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    row = await crud.upsert_user_progress(db, current_user.id, payload.profile)
    return ProgressResponse(profile=row.profile, updated_at=row.updated_at)
