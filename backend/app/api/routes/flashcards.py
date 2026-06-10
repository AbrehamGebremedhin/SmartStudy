from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.curriculum_validation import validate_curriculum_params
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import FlashcardRequest
from app.schemas.responses import FlashcardResponse
from app.security.rate_limiter import limiter
from app.services.cache import _parse_token_usage, compute_request_hash
from app.services.generation import run_generate_flashcards


def _format_chat_context(messages) -> str:
    lines, concepts = [], []
    for m in messages:
        if m.role == "user":
            lines.append(f"Student: {m.content}")
        elif m.role == "assistant":
            lines.append(f"Teacher: {m.content}")
            for c in (m.key_concepts or []):
                if c not in concepts:
                    concepts.append(c)
    result = "\n".join(lines)
    if concepts:
        result += f"\n\nKey concepts covered: {', '.join(concepts)}"
    return result

router = APIRouter(prefix="/flashcards", tags=["Flashcards"])


@router.post("/generate", response_model=FlashcardResponse)
@limiter.limit("200/day")
@limiter.limit("10/minute")
async def generate_flashcards(
    request: Request,
    body: FlashcardRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlashcardResponse:
    validate_curriculum_params(body.subject, body.grade, body.unit)

    note_content: dict | None = None
    chat_context: str | None = None

    if body.note_id:
        note_gen = await crud.get_generation_for_user(db, current_user.id, body.note_id, "notes")
        if not note_gen:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
        note_content = note_gen.content.get("notes")

    if body.chat_session_id:
        chat_session = await crud.get_chat_session_with_messages(db, body.chat_session_id, current_user.id)
        if not chat_session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")
        chat_context = _format_chat_context(chat_session.messages)

    params = {
        "subject": body.subject,
        "grade": body.grade,
        "unit": body.unit,
        "topic": body.topic,
        "note_id": str(body.note_id) if body.note_id else None,
        "chat_session_id": str(body.chat_session_id) if body.chat_session_id else None,
        "num_cards": body.num_cards,
        "difficulty": body.difficulty,
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
            difficulty=cached.content.get("difficulty", body.difficulty),
        )

    result = await run_generate_flashcards(
        subject=body.subject,
        grade=body.grade,
        unit=body.unit,
        topic=body.topic,
        num_cards=body.num_cards,
        difficulty=body.difficulty,
        note_content=note_content,
        chat_context=chat_context,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))

    generation = await crud.save_generation(
        db,
        generation_type="flashcard",
        request_hash=request_hash,
        request_params=params,
        content={"flashcards": result["flashcards"], "difficulty": result.get("difficulty", body.difficulty)},
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
        difficulty=result.get("difficulty", body.difficulty),
        token_usage=result.get("token_usage"),
    )
