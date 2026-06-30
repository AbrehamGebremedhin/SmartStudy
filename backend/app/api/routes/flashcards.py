import math
import random

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.curriculum_validation import validate_curriculum_params
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import FlashcardRequest
from app.schemas.responses import FlashcardResponse
from app.security.rate_limiter import limiter
from app.services.cache import POOL_FRESH_RATIO, _parse_token_usage, compute_request_hash
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


# ── Spaced repetition (Leitner) ───────────────────────────────────────────────

class ReviewRequest(BaseModel):
    front: str = Field(..., min_length=1, max_length=2000)
    back: str = Field(..., min_length=1, max_length=4000)
    topic: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=50)
    known: bool


class ReviewState(BaseModel):
    box: int
    due_at: str


class DueCard(BaseModel):
    front: str
    back: str
    topic: str | None
    subject: str | None
    box: int
    due_at: str


@router.post("/review", response_model=ReviewState)
@limiter.limit("1000/day")
@limiter.limit("60/minute")
async def record_review(
    request: Request,
    body: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewState:
    row = await crud.record_flashcard_review(
        db, current_user.id, front=body.front, back=body.back,
        topic=body.topic, subject=body.subject, known=body.known,
    )
    return ReviewState(box=row.box, due_at=row.due_at.isoformat())


@router.get("/due", response_model=list[DueCard])
async def due_flashcards(
    subject: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DueCard]:
    rows = await crud.get_due_flashcards(db, current_user.id, subject=subject, limit=limit)
    return [
        DueCard(front=r.front, back=r.back, topic=r.topic, subject=r.subject,
                box=r.box, due_at=r.due_at.isoformat())
        for r in rows
    ]


async def _record_cache_hit(db: AsyncSession, user_id, generation_id) -> None:
    await crud.link_user_generation(db, user_id, generation_id, was_cache_hit=True)
    await db.commit()


@router.post("/generate", response_model=FlashcardResponse)
@limiter.limit("200/day")
@limiter.limit("10/minute")
async def generate_flashcards(
    request: Request,
    body: FlashcardRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlashcardResponse:
    validate_curriculum_params(body.subject, body.grade, body.unit)

    # Contextual requests (note/chat grounded) keep exact-hash caching — items
    # are anchored to specific source material and shouldn't mix with the pool.
    if body.note_id or body.chat_session_id:
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
            background_tasks.add_task(_record_cache_hit, db, current_user.id, cached.id)
            return FlashcardResponse(
                generation_id=cached.id,
                was_cache_hit=True,
                flashcards=cached.content["flashcards"],
                difficulty=cached.content.get("difficulty", body.difficulty),
            )
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
        result = await run_generate_flashcards(
            subject=body.subject, grade=body.grade, unit=body.unit, topic=body.topic,
            num_cards=body.num_cards, difficulty=body.difficulty,
            note_content=note_content, chat_context=chat_context,
        )
        if result.get("error"):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])
        input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))
        generation = await crud.save_generation(
            db, generation_type="flashcard", request_hash=request_hash, request_params=params,
            content={"flashcards": result["flashcards"], "difficulty": result.get("difficulty", body.difficulty)},
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
        )
        await crud.link_user_generation(db, current_user.id, generation.id, was_cache_hit=False)
        await db.commit()
        return FlashcardResponse(
            generation_id=generation.id, was_cache_hit=False,
            flashcards=result["flashcards"], difficulty=result.get("difficulty", body.difficulty),
            token_usage=result.get("token_usage"),
        )

    # Generic (no context): pool existing items + always generate POOL_FRESH_RATIO fresh.
    # Each call adds new items to the shared pool so variety grows over time.
    topic_params = {
        "subject": body.subject,
        "grade": body.grade,
        "unit": body.unit,
        "topic": body.topic,
        "difficulty": body.difficulty,
    }
    topic_hash = compute_request_hash(topic_params)

    pool = await crud.get_pooled_items(db, topic_hash, "flashcard", "flashcards")

    # Deduplicate pool by front-side text
    seen: set[str] = set()
    unique_pool: list = []
    for card in pool:
        k = card.get("front", "")
        if k not in seen:
            seen.add(k)
            unique_pool.append(card)

    # At most (1 - POOL_FRESH_RATIO) of the requested count comes from the pool
    max_reuse = math.floor(body.num_cards * (1 - POOL_FRESH_RATIO))
    reuse_count = min(max_reuse, len(unique_pool))
    fresh_count = body.num_cards - reuse_count

    result = await run_generate_flashcards(
        subject=body.subject, grade=body.grade, unit=body.unit, topic=body.topic,
        num_cards=fresh_count, difficulty=body.difficulty,
        note_content=None, chat_context=None,
    )
    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    input_tokens, output_tokens, cost_usd = _parse_token_usage(result.get("token_usage"))
    generation = await crud.save_generation(
        db, generation_type="flashcard", request_hash=topic_hash, request_params=topic_params,
        content={"flashcards": result["flashcards"], "difficulty": result.get("difficulty", body.difficulty)},
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
    )
    await crud.link_user_generation(db, current_user.id, generation.id, was_cache_hit=False)
    await db.commit()

    reused = random.sample(unique_pool, reuse_count) if reuse_count > 0 else []
    all_cards = result["flashcards"] + reused
    random.shuffle(all_cards)

    return FlashcardResponse(
        generation_id=generation.id,
        was_cache_hit=False,
        flashcards=all_cards,
        difficulty=result.get("difficulty", body.difficulty),
        token_usage=result.get("token_usage"),
    )
