import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import func

from app.config import settings
from app.db.models import ChatMessage, ChatSession, Generation, SecurityEvent, User, UserGeneration


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def get_or_create_user(db: AsyncSession, clerk_id: str, email: str) -> tuple[User, bool]:
    """Return (user, created) where created=True if the user was just created."""
    result = await db.execute(select(User).where(User.google_id == clerk_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(google_id=clerk_id, email=email)
        db.add(user)
        await db.flush()
        await db.commit()
        await db.refresh(user)
        return user, True

    user.last_seen_at = datetime.now(timezone.utc)
    user.email = email
    await db.commit()
    await db.refresh(user)
    return user, False


# ---------------------------------------------------------------------------
# Generations (shared content pool)
# ---------------------------------------------------------------------------

async def get_cached_generation(
    db: AsyncSession,
    request_hash: str,
    generation_type: str,
) -> Generation | None:
    result = await db.execute(
        select(Generation)
        .where(Generation.request_hash == request_hash, Generation.type == generation_type)
        .order_by(func.random())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def save_generation(
    db: AsyncSession,
    generation_type: str,
    request_hash: str,
    request_params: dict,
    content: dict,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> Generation:
    generation = Generation(
        type=generation_type,
        request_hash=request_hash,
        request_params=request_params,
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    db.add(generation)
    await db.flush()
    await db.refresh(generation)
    return generation


async def link_user_generation(
    db: AsyncSession,
    user_id: uuid.UUID,
    generation_id: uuid.UUID,
    was_cache_hit: bool,
) -> UserGeneration:
    ug = UserGeneration(
        user_id=user_id,
        generation_id=generation_id,
        was_cache_hit=was_cache_hit,
    )
    db.add(ug)
    await db.flush()
    await db.refresh(ug)
    return ug


async def get_user_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    generation_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[tuple[UserGeneration, Generation]]:
    query = (
        select(UserGeneration, Generation)
        .join(Generation, UserGeneration.generation_id == Generation.id)
        .where(UserGeneration.user_id == user_id)
    )
    if generation_type:
        query = query.where(Generation.type == generation_type)

    query = query.order_by(UserGeneration.accessed_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return result.all()


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------

async def create_chat_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    subject: str,
    grade: int | None,
    title: str,
) -> ChatSession:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.chat_session_ttl_hours)
    session = ChatSession(
        user_id=user_id,
        subject=subject,
        grade=grade,
        title=title,
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def get_chat_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.expires_at > datetime.now(timezone.utc),
        )
    )
    return result.scalar_one_or_none()


async def get_chat_session_with_messages(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ChatSession | None:
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.expires_at > datetime.now(timezone.utc),
        )
    )
    return result.scalar_one_or_none()


async def get_user_chat_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(
            ChatSession.user_id == user_id,
            ChatSession.expires_at > datetime.now(timezone.utc),
        )
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def update_chat_session_title(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
) -> bool:
    session = await get_chat_session(db, session_id, user_id)
    if session is None:
        return False
    session.title = title
    session.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def add_chat_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    content: str,
    key_concepts: list[str],
) -> ChatMessage:
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        key_concepts=key_concepts,
    )
    db.add(message)

    # bump updated_at on the session
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(message)
    return message


# ---------------------------------------------------------------------------
# Security events
# ---------------------------------------------------------------------------

async def log_security_event(
    db: AsyncSession,
    endpoint: str,
    field_name: str,
    event_type: str,
    user_id: uuid.UUID | None = None,
) -> None:
    """Fire-and-forget write; caller must commit."""
    event = SecurityEvent(
        user_id=user_id,
        endpoint=endpoint,
        field_name=field_name,
        event_type=event_type,
    )
    db.add(event)
    await db.flush()
