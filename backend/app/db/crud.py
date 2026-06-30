import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (ChatMessage, ChatSession, ExamQuestion, FlashcardReview, Generation,
                           SecurityEvent, User, UserGeneration, UserProgress)
from app.services import srs


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def get_or_create_user(db: AsyncSession, clerk_id: str, email: str) -> tuple[User, bool]:
    """Return (user, created) where created=True if the user was just created."""
    result = await db.execute(select(User).where(User.google_id == clerk_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Two concurrent first-logins of the same id both see None and race to
        # INSERT. Let the DB arbitrate: the loser's row is skipped (no exception)
        # and `created` reflects who actually inserted (rowcount 1 vs 0).
        ins = await db.execute(
            pg_insert(User).values(google_id=clerk_id, email=email)
            .on_conflict_do_nothing(index_elements=["google_id"])
        )
        await db.commit()
        user = (await db.execute(select(User).where(User.google_id == clerk_id))).scalar_one()
        return user, ins.rowcount == 1

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
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_pooled_items(
    db: AsyncSession,
    topic_hash: str,
    generation_type: str,
    item_key: str,
) -> list:
    """Return all items from every generation sharing the given topic hash."""
    result = await db.execute(
        select(Generation)
        .where(Generation.request_hash == topic_hash, Generation.type == generation_type)
    )
    items = []
    for gen in result.scalars().all():
        items.extend(gen.content.get(item_key, []))
    return items


# ---------------------------------------------------------------------------
# Past-exam questions (Past Exams practice mode)
# ---------------------------------------------------------------------------

async def get_exam_subjects(db: AsyncSession) -> list[tuple[str, int]]:
    """Subjects that have enriched exam questions, with counts."""
    result = await db.execute(
        select(ExamQuestion.subject, func.count(ExamQuestion.id))
        .where(ExamQuestion.correct_answer.isnot(None))
        .group_by(ExamQuestion.subject)
        .order_by(ExamQuestion.subject)
    )
    return [(s, n) for s, n in result.all()]


async def get_exam_questions(
    db: AsyncSession,
    subject: str,
    year: str | None = None,
    grade: int | None = None,
    unit: str | None = None,
    limit: int = 20,
    include_review: bool = False,
) -> list[ExamQuestion]:
    """Random sample of enriched exam questions matching the filters."""
    conds = [ExamQuestion.subject == subject, ExamQuestion.correct_answer.isnot(None)]
    if year:
        conds.append(ExamQuestion.year == year)
    if grade is not None:
        conds.append(ExamQuestion.grade == grade)
    if unit is not None:
        conds.append(ExamQuestion.unit == unit)
    if not include_review:
        conds.append(ExamQuestion.needs_review.is_(False))
    result = await db.execute(
        select(ExamQuestion).where(*conds).order_by(func.random()).limit(limit)
    )
    return list(result.scalars().all())


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


async def get_generation_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    generation_id: uuid.UUID,
    generation_type: str | None = None,
) -> Generation | None:
    """Return a Generation only if it belongs to the given user."""
    query = (
        select(Generation)
        .join(UserGeneration, UserGeneration.generation_id == Generation.id)
        .where(UserGeneration.user_id == user_id, Generation.id == generation_id)
    )
    if generation_type:
        query = query.where(Generation.type == generation_type)
    result = await db.execute(query)
    return result.scalar_one_or_none()


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

    # bump updated_at on the session without a round-trip SELECT
    await db.execute(
        update(ChatSession)
        .where(ChatSession.id == session_id)
        .values(updated_at=datetime.now(timezone.utc))
    )

    await db.flush()
    await db.refresh(message)
    return message


# ---------------------------------------------------------------------------
# User progress (gamification profile)
# ---------------------------------------------------------------------------

async def get_user_progress(db: AsyncSession, user_id: uuid.UUID) -> UserProgress | None:
    result = await db.execute(select(UserProgress).where(UserProgress.user_id == user_id))
    return result.scalar_one_or_none()


async def upsert_user_progress(db: AsyncSession, user_id: uuid.UUID, profile: dict) -> UserProgress:
    """Insert-or-replace the user's progress blob (last-write-wins)."""
    await db.execute(
        pg_insert(UserProgress)
        .values(user_id=user_id, profile=profile)
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={"profile": profile, "updated_at": datetime.now(timezone.utc)},
        )
    )
    await db.commit()
    return (await get_user_progress(db, user_id))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Flashcard spaced repetition (Leitner)
# ---------------------------------------------------------------------------

async def record_flashcard_review(
    db: AsyncSession,
    user_id: uuid.UUID,
    front: str,
    back: str,
    topic: str | None,
    subject: str | None,
    known: bool,
) -> FlashcardReview:
    """Upsert Leitner state for a card: advance/reset its box and reschedule."""
    key = srs.card_key(front)
    existing = await db.get(FlashcardReview, (user_id, key))
    current_box = existing.box if existing else 1
    box = srs.next_box(current_box, known)
    due = srs.due_at(box)
    await db.execute(
        pg_insert(FlashcardReview)
        .values(
            user_id=user_id, card_key=key, front=front, back=back,
            topic=topic, subject=subject, box=box, due_at=due,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "card_key"],
            set_={
                "box": box, "due_at": due, "back": back,
                "topic": topic, "subject": subject,
                "last_rated_at": datetime.now(timezone.utc),
            },
        )
    )
    await db.commit()
    return await db.get(FlashcardReview, (user_id, key))  # type: ignore[return-value]


async def get_due_flashcards(
    db: AsyncSession,
    user_id: uuid.UUID,
    subject: str | None = None,
    limit: int = 20,
) -> list[FlashcardReview]:
    conds = [FlashcardReview.user_id == user_id, FlashcardReview.due_at <= datetime.now(timezone.utc)]
    if subject:
        conds.append(FlashcardReview.subject == subject)
    result = await db.execute(
        select(FlashcardReview).where(*conds).order_by(FlashcardReview.due_at).limit(limit)
    )
    return list(result.scalars().all())


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
