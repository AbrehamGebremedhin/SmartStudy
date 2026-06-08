from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import FlashcardRequest
from app.schemas.responses import FlashcardResponse
from app.services.cache import _parse_token_usage, compute_request_hash
from app.services.generation import run_generate_flashcards

router = APIRouter(prefix="/flashcards", tags=["Flashcards"])


@router.post("/generate", response_model=FlashcardResponse)
async def generate_flashcards(
    request: FlashcardRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlashcardResponse:
    params = {
        "subject": request.subject,
        "grade": request.grade,
        "unit": request.unit,
        "topic": request.topic,
        "num_cards": request.num_cards,
        "difficulty": request.difficulty,
    }
    request_hash = compute_request_hash(params)

    cached = await crud.get_cached_generation(db, request_hash, "flashcard")

    if cached:
        await crud.link_user_generation(db, current_user.id, cached.id, was_cache_hit=True)
        await db.commit()
        return FlashcardResponse(
            generation_id=cached.id,
            was_cache_hit=True,
            flashcards=cached.content["flashcards"],
            difficulty=cached.content.get("difficulty", request.difficulty),
        )

    result = await run_generate_flashcards(
        subject=request.subject,
        grade=request.grade,
        unit=request.unit,
        topic=request.topic,
        num_cards=request.num_cards,
        difficulty=request.difficulty,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))

    generation = await crud.save_generation(
        db,
        generation_type="flashcard",
        request_hash=request_hash,
        request_params=params,
        content={"flashcards": result["flashcards"], "difficulty": result.get("difficulty", request.difficulty)},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    await crud.link_user_generation(db, current_user.id, generation.id, was_cache_hit=False)
    await db.commit()

    return FlashcardResponse(
        generation_id=generation.id,
        was_cache_hit=False,
        flashcards=result["flashcards"],
        difficulty=result.get("difficulty", request.difficulty),
        token_usage=result.get("token_usage"),
    )
