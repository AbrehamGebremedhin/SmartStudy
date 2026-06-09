from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import MCQRequest
from app.schemas.responses import MCQResponse
from app.security.rate_limiter import limiter
from app.services.cache import _parse_token_usage, compute_request_hash
from app.services.generation import run_generate_mcqs

router = APIRouter(prefix="/mcq", tags=["MCQ"])


@router.post("/generate", response_model=MCQResponse)
@limiter.limit("200/day")
@limiter.limit("10/minute")
async def generate_mcqs(
    request: Request,
    body: MCQRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCQResponse:
    params = {
        "subject": body.subject,
        "grade": body.grade,
        "unit": body.unit,
        "num_questions": body.num_questions,
        "difficulty": body.difficulty,
    }
    request_hash = compute_request_hash(params)

    cached = await crud.get_cached_generation(db, request_hash, "mcq")

    if cached:
        ug = await crud.link_user_generation(db, current_user.id, cached.id, was_cache_hit=True)
        await db.commit()
        return MCQResponse(
            generation_id=cached.id,
            was_cache_hit=True,
            questions=cached.content["questions"],
            difficulty=cached.content.get("difficulty", body.difficulty),
        )

    result = await run_generate_mcqs(
        subject=body.subject,
        grade=body.grade,
        unit=body.unit,
        num_questions=body.num_questions,
        difficulty=body.difficulty,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))

    generation = await crud.save_generation(
        db,
        generation_type="mcq",
        request_hash=request_hash,
        request_params=params,
        content={"questions": result["questions"], "difficulty": result.get("difficulty", body.difficulty)},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    await crud.link_user_generation(db, current_user.id, generation.id, was_cache_hit=False)
    await db.commit()

    return MCQResponse(
        generation_id=generation.id,
        was_cache_hit=False,
        questions=result["questions"],
        difficulty=result.get("difficulty", body.difficulty),
        token_usage=result.get("token_usage"),
    )
