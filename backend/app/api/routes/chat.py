import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.curriculum_validation import CROSS_GRADE_SUBJECTS, VALID_COMBINATIONS
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import ChatMessageRequest, ChatSessionCreateRequest, UpdateSessionTitleRequest
from app.schemas.responses import ChatReplyResponse, ChatSessionDetailResponse, ChatSessionResponse
from app.security.rate_limiter import limiter
from app.services.generation import run_chat_response

router = APIRouter(prefix="/chat", tags=["Chat"])

PaginationLimit = Annotated[int, Query(ge=1, le=200, description="Number of items to return")]
PaginationOffset = Annotated[int, Query(ge=0, le=1_000_000, description="Number of items to skip")]


def _check_question_scope(question: str, subject: str, grade: int | None) -> str | None:
    """Return a user-facing message if the question explicitly references out-of-scope content.

    Returns None when nothing unusual is detected so normal flow continues.
    """
    # Detect explicit references to a different grade
    grade_matches = re.findall(r"\bgrade\s*(\d+)\b", question, re.IGNORECASE)
    for raw in grade_matches:
        ref_grade = int(raw)
        if grade is not None and ref_grade != grade and ref_grade in VALID_COMBINATIONS:
            return (
                f"This session covers {subject.title()} for Grade {grade}. "
                f"Grade {ref_grade} content isn't available here — "
                f"please start a new session and select Grade {ref_grade} to ask about it."
            )

    # Detect unit numbers outside the valid range for this session
    if (
        grade is not None
        and subject not in CROSS_GRADE_SUBJECTS
        and subject in VALID_COMBINATIONS.get(grade, {})
    ):
        max_units = VALID_COMBINATIONS[grade][subject]
        unit_matches = re.findall(r"\bunit\s*(\d+)\b", question, re.IGNORECASE)
        for raw in unit_matches:
            ref_unit = int(raw)
            if ref_unit < 1 or ref_unit > max_units:
                return (
                    f"{subject.title()} Grade {grade} covers units 1–{max_units}. "
                    f"Unit {ref_unit} doesn't exist in this curriculum."
                )

    return None


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: ChatSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    session = await crud.create_chat_session(
        db,
        user_id=current_user.id,
        subject=request.subject,
        grade=request.grade,
        title=request.title,
    )
    await db.commit()
    return ChatSessionResponse.model_validate(session)


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionResponse]:
    sessions = await crud.get_user_chat_sessions(db, current_user.id, limit=limit, offset=offset)
    return [ChatSessionResponse.model_validate(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionDetailResponse:
    session = await crud.get_chat_session_with_messages(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return ChatSessionDetailResponse.model_validate(session)


@router.put("/sessions/{session_id}/title", response_model=ChatSessionResponse)
async def update_title(
    session_id: uuid.UUID,
    request: UpdateSessionTitleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    updated = await crud.update_chat_session_title(db, session_id, current_user.id, request.title)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    session = await crud.get_chat_session(db, session_id, current_user.id)
    return ChatSessionResponse.model_validate(session)


@router.get("/sessions/{session_id}/context")
async def get_session_context(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the most likely grade and unit for this session by querying the vector DB."""
    session = await crud.get_chat_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    from app.services.generation import run_chat_context
    result = await run_chat_context(subject=session.subject, grade=session.grade, title=session.title)
    return {"grade": result.get("grade"), "unit": result.get("unit")}


@router.post("/sessions/{session_id}/messages", response_model=ChatReplyResponse)
@limiter.limit("500/day")
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    session_id: uuid.UUID,
    body: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatReplyResponse:
    session = await crud.get_chat_session_with_messages(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    prior_messages = session.messages if hasattr(session, "messages") else []
    chat_history_str = "\n".join(
        f"{m.role.capitalize()}: {m.content}"
        for m in prior_messages
        if m.content
    )

    # Pre-check: detect explicit grade/unit references outside this session's scope
    scope_msg = _check_question_scope(body.question, session.subject, session.grade)
    if scope_msg:
        await crud.add_chat_message(db, session_id, role="user", content=body.question, key_concepts=[])
        await crud.add_chat_message(db, session_id, role="assistant", content=scope_msg, key_concepts=[])
        await db.commit()
        return ChatReplyResponse(
            session_id=session_id,
            title=session.title,
            current_response={"answer": scope_msg, "key_concepts": [], "follow_up_questions": []},
            token_usage=None,
        )

    await crud.add_chat_message(db, session_id, role="user", content=body.question, key_concepts=[])

    result = await run_chat_response(
        subject=session.subject,
        question=body.question,
        session_id=None,
        grade=session.grade,
        chat_history_str=chat_history_str,
    )

    if result.get("error"):
        error_msg = result["error"]
        # Empty context means no curriculum content matched — return a helpful chat message
        # instead of an HTTP error so the conversation stays intact.
        if "No relevant documents found" in error_msg:
            no_ctx_msg = (
                f"I couldn't find curriculum content matching your question for "
                f"{session.subject.title()}"
                + (f" Grade {session.grade}" if session.grade else "")
                + ". Try rephrasing, or check that the topic is covered in this subject."
            )
            await crud.add_chat_message(
                db, session_id, role="assistant", content=no_ctx_msg, key_concepts=[]
            )
            await db.commit()
            return ChatReplyResponse(
                session_id=session_id,
                title=session.title,
                current_response={"answer": no_ctx_msg, "key_concepts": [], "follow_up_questions": []},
                token_usage=None,
            )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error_msg)

    if result.get("out_of_scope"):
        history = result.get("conversation_history", [])
        assistant_msg = next((m for m in reversed(history) if m["role"] == "assistant"), {})
        out_of_scope_text = assistant_msg.get("message", "")
        await crud.add_chat_message(
            db, session_id, role="assistant", content=out_of_scope_text, key_concepts=[]
        )
        await db.commit()
        return ChatReplyResponse(
            session_id=session_id,
            title=session.title,
            current_response={"answer": out_of_scope_text, "key_concepts": [], "follow_up_questions": []},
            token_usage=result.get("token_usage"),
        )

    current_response: dict = result.get("current_response", {})
    key_concepts: list[str] = current_response.get("key_concepts", [])

    history = result.get("conversation_history", [])
    assistant_msg = next((m for m in reversed(history) if m["role"] == "assistant"), {})
    answer_text = assistant_msg.get("message", "")
    current_response["answer"] = answer_text

    await crud.add_chat_message(
        db,
        session_id,
        role="assistant",
        content=answer_text,
        key_concepts=key_concepts,
    )

    suggested_title: str | None = result.get("title")
    if suggested_title and suggested_title != session.title and session.title == "New Chat":
        await crud.update_chat_session_title(db, session_id, current_user.id, suggested_title)

    await db.commit()

    return ChatReplyResponse(
        session_id=session_id,
        title=suggested_title or session.title,
        current_response=current_response,
        context_grade=result.get("context_grade"),
        context_unit=result.get("context_unit"),
        token_usage=result.get("token_usage"),
    )
