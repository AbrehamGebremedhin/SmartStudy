from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.responses import HistoryItemResponse

router = APIRouter(prefix="/history", tags=["History"])

PaginationLimit = Annotated[int, Query(ge=1, le=200, description="Number of items to return")]
PaginationOffset = Annotated[int, Query(ge=0, le=1_000_000, description="Number of items to skip")]


@router.get("/{generation_type}", response_model=list[HistoryItemResponse])
async def get_history(
    generation_type: Literal["mcq", "flashcard", "notes"],
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[HistoryItemResponse]:
    rows = await crud.get_user_history(
        db, current_user.id, generation_type=generation_type, limit=limit, offset=offset
    )
    return [
        HistoryItemResponse(
            user_generation_id=ug.id,
            generation_id=gen.id,
            type=gen.type,
            request_params=gen.request_params,
            was_cache_hit=ug.was_cache_hit,
            accessed_at=ug.accessed_at,
        )
        for ug, gen in rows
    ]


@router.get("/", response_model=list[HistoryItemResponse])
async def get_all_history(
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[HistoryItemResponse]:
    rows = await crud.get_user_history(db, current_user.id, generation_type=None, limit=limit, offset=offset)
    return [
        HistoryItemResponse(
            user_generation_id=ug.id,
            generation_id=gen.id,
            type=gen.type,
            request_params=gen.request_params,
            was_cache_hit=ug.was_cache_hit,
            accessed_at=ug.accessed_at,
        )
        for ug, gen in rows
    ]
