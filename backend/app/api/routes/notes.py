import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.curriculum_validation import validate_curriculum_params
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import NoteChatRequest, NotesRequest
from app.schemas.responses import NoteChatResponse, NotesResponse
from app.security.rate_limiter import limiter
from app.services.cache import _parse_token_usage, compute_request_hash
from app.services.generation import run_generate_notes, run_note_chat


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

router = APIRouter(prefix="/notes", tags=["Notes"])


async def _record_cache_hit(db: AsyncSession, user_id, generation_id) -> None:
    await crud.link_user_generation(db, user_id, generation_id, was_cache_hit=True)
    await db.commit()


@router.post("/generate", response_model=NotesResponse)
@limiter.limit("200/day")
@limiter.limit("10/minute")
async def generate_notes(
    request: Request,
    body: NotesRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotesResponse:
    validate_curriculum_params(body.subject, body.grade, body.unit)

    # Hash uses IDs only (not content), so compute it before any DB calls.
    params = {
        "subject": body.subject,
        "topic": body.topic,
        "grade": body.grade,
        "unit": body.unit,
        "chat_session_id": str(body.chat_session_id) if body.chat_session_id else None,
        "version": body.version,
    }
    request_hash = compute_request_hash(params)

    # Check cache before loading chat context — skips a DB round-trip on hits.
    cached = await crud.get_cached_generation(db, request_hash, "notes")
    if cached:
        background_tasks.add_task(_record_cache_hit, db, current_user.id, cached.id)
        return NotesResponse(
            generation_id=cached.id,
            was_cache_hit=True,
            notes=cached.content["notes"],
        )

    # Cache miss — load chat context only now that we know generation is needed.
    chat_context: str | None = None
    if body.chat_session_id:
        chat_session = await crud.get_chat_session_with_messages(db, body.chat_session_id, current_user.id)
        if not chat_session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")
        chat_context = _format_chat_context(chat_session.messages)

    # Release the DB connection during the ~30-50s generation so it isn't pinned
    # idle-in-transaction (which would cap concurrent generations at the pool size).
    # The cache check + chat-context read above are read-only; the save re-acquires a conn.
    await db.commit()
    result = await run_generate_notes(
        subject=body.subject,
        topic=body.topic,
        grade=body.grade,
        unit=body.unit,
        version=body.version,
        chat_context=chat_context,
    )

    if result.get("error"):
        error_code = result["error"]
        if error_code == "topic_not_in_unit":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=result.get("message", error_code),
            )
        if "No relevant documents found" in str(error_code):
            scope = body.subject.title()
            if body.grade:
                scope += f" Grade {body.grade}"
            if body.unit:
                scope += f" Unit {body.unit}"
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"No curriculum content found for {scope}. "
                    "Check that the subject, grade, and unit are correct, "
                    "then try rephrasing the topic."
                ),
            )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error_code)

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


@router.post("/{generation_id}/chat", response_model=NoteChatResponse)
@limiter.limit("500/day")
@limiter.limit("30/minute")
async def chat_with_note(
    request: Request,
    generation_id: uuid.UUID,
    body: NoteChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteChatResponse:
    note_gen = await crud.get_generation_for_user(db, current_user.id, generation_id, "notes")
    if not note_gen:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")

    note_content = note_gen.content.get("notes", {})
    subject = note_gen.request_params.get("subject", "")

    chat_history_str = "\n".join(
        f"{'Student' if m.get('role') == 'user' else 'Teacher'}: {m.get('content', '')}"
        for m in body.chat_history
    )

    result = await run_note_chat(
        note_content=note_content,
        subject=subject,
        question=body.question,
        chat_history_str=chat_history_str,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    return NoteChatResponse(
        answer=result["answer"],
        key_concepts=result.get("key_concepts", []),
        follow_up_questions=result.get("follow_up_questions", []),
        token_usage=result.get("token_usage"),
    )
