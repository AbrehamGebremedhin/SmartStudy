import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
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

    await crud.add_chat_message(db, session_id, role="user", content=body.question, key_concepts=[])

    result = await run_chat_response(
        subject=session.subject,
        question=body.question,
        session_id=None,
        grade=session.grade,
        chat_history_str=chat_history_str,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

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
            current_response={"key_concepts": [], "follow_up_questions": []},
            token_usage=result.get("token_usage"),
        )

    current_response: dict = result.get("current_response", {})
    key_concepts: list[str] = current_response.get("key_concepts", [])

    history = result.get("conversation_history", [])
    assistant_msg = next((m for m in reversed(history) if m["role"] == "assistant"), {})
    answer_text = assistant_msg.get("message", "")

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
        token_usage=result.get("token_usage"),
    )
