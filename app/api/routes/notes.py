from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import NotesRequest
from app.schemas.responses import NotesResponse
from app.services.cache import _parse_token_usage, compute_request_hash
from app.services.generation import run_generate_notes

router = APIRouter(prefix="/notes", tags=["Notes"])


@router.post("/generate", response_model=NotesResponse)
async def generate_notes(
    request: NotesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotesResponse:
    params = {
        "subject": request.subject,
        "topic": request.topic,
        "grade": request.grade,
        "unit": request.unit,
        "version": request.version,
    }
    request_hash = compute_request_hash(params)

    cached = await crud.get_cached_generation(db, request_hash, "notes")

    if cached:
        await crud.link_user_generation(db, current_user.id, cached.id, was_cache_hit=True)
        await db.commit()
        return NotesResponse(
            generation_id=cached.id,
            was_cache_hit=True,
            notes=cached.content["notes"],
        )

    result = await run_generate_notes(
        subject=request.subject,
        topic=request.topic,
        grade=request.grade,
        unit=request.unit,
        version=request.version,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))

    generation = await crud.save_generation(
        db,
        generation_type="notes",
        request_hash=request_hash,
        request_params=params,
        content={"notes": result["notes"]},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    await crud.link_user_generation(db, current_user.id, generation.id, was_cache_hit=False)
    await db.commit()

    return NotesResponse(
        generation_id=generation.id,
        was_cache_hit=False,
        notes=result["notes"],
        token_usage=result.get("token_usage"),
    )
