import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, cast, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (Bookmark, ChatActivity, ChatMessage, ChatSession, ExamQuestion, FlashcardReview,
                           Generation, Mistake, QuestionAttempt, SecurityEvent, User,
                           UserGeneration, UserProgress)
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
    max_generations: int = 30,
) -> list:
    """Return items from the most recent generations sharing the given topic hash.

    Capped so a popular topic doesn't pull an ever-growing set of full JSONB
    content rows into memory each request. Recent bias is fine (fresher items);
    the caller dedups and samples anyway.
    ponytail: newest-N cap; raise it if pools feel too shallow.
    """
    result = await db.execute(
        select(Generation.content)
        .where(Generation.request_hash == topic_hash, Generation.type == generation_type)
        .order_by(Generation.created_at.desc())
        .limit(max_generations)
    )
    items = []
    for content in result.scalars().all():
        items.extend(content.get(item_key, []))
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
    # The upsert runs via Core, so the ORM instance loaded above is stale after
    # commit (expire_on_commit=False). Refresh it to return the written box/due,
    # not the pre-update values.
    row = await db.get(FlashcardReview, (user_id, key))
    await db.refresh(row)
    return row  # type: ignore[return-value]


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
# Question attempts + per-unit mastery analytics
# ---------------------------------------------------------------------------

async def record_attempts(db: AsyncSession, user_id: uuid.UUID, attempts: list[dict]) -> None:
    """Append a batch of answered questions.

    Each dict: subject, grade, unit, topic, correct (+ optional source,
    question_id, score — see QuestionAttempt for their semantics).
    """
    if not attempts:
        return
    db.add_all([
        QuestionAttempt(
            user_id=user_id, subject=a["subject"], grade=a.get("grade"),
            unit=a.get("unit"), topic=a.get("topic"), correct=a["correct"],
            source=a.get("source"), question_id=a.get("question_id"), score=a.get("score"),
        )
        for a in attempts
    ])
    await db.commit()


async def get_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    subject: str | None = None,
    by_source: bool = False,
) -> list[dict]:
    """Per-(subject, grade, unit) accuracy, weakest first. Grade/unit may be null.

    Review attempts (recall minutes after reading the notes — inflated) and drill
    attempts (retakes) are excluded so "weak areas" stays honest; they appear in
    trends only. With by_source the rows split per source (NULL = legacy), which
    makes practice-vs-mock accuracy comparable per unit client-side.
    """
    conds = [
        QuestionAttempt.user_id == user_id,
        # NOT IN is NULL-hostile in SQL; keep the legacy-NULL rows explicitly.
        or_(QuestionAttempt.source.is_(None), QuestionAttempt.source.notin_(("review", "drill"))),
    ]
    if subject:
        conds.append(QuestionAttempt.subject == subject)
    total = func.count()
    correct = func.sum(cast(QuestionAttempt.correct, Integer))
    group = [QuestionAttempt.subject, QuestionAttempt.grade, QuestionAttempt.unit]
    if by_source:
        group.append(QuestionAttempt.source)
    result = await db.execute(
        select(*group, total.label("total"), correct.label("correct"))
        .where(*conds)
        .group_by(*group)
    )
    rows = []
    for row in result.all():
        s, g, u, *rest = row
        src = rest[0] if by_source else None
        t, c = rest[-2], rest[-1]
        rows.append({"subject": s, "grade": g, "unit": u, "source": src,
                     "total": t, "correct": int(c or 0),
                     "accuracy": round((int(c or 0) / t) * 100) if t else 0})
    rows.sort(key=lambda r: r["accuracy"])  # weakest first
    return rows


async def get_trends(
    db: AsyncSession,
    user_id: uuid.UUID,
    days: int = 30,
    subject: str | None = None,
) -> list[dict]:
    """Per-(day, source) attempt counts for the trend chart, oldest first.

    Days are bucketed in Africa/Addis_Ababa (UTC+3), not UTC — evening study
    sessions are most sessions, and UTC boundaries would split them across the
    wrong day. Source NULL (legacy rows) comes through as its own bucket rather
    than being dropped, so existing users' history isn't understated.
    """
    local_day = func.date_trunc("day", func.timezone("Africa/Addis_Ababa", QuestionAttempt.created_at))
    conds = [
        QuestionAttempt.user_id == user_id,
        QuestionAttempt.created_at >= datetime.now(timezone.utc) - timedelta(days=days),
    ]
    if subject:
        conds.append(QuestionAttempt.subject == subject)
    total = func.count()
    correct = func.sum(cast(QuestionAttempt.correct, Integer))
    result = await db.execute(
        select(local_day.label("day"), QuestionAttempt.source,
               total.label("total"), correct.label("correct"))
        .where(*conds)
        .group_by(local_day, QuestionAttempt.source)
        .order_by(local_day)
    )
    return [
        {"date": d.strftime("%Y-%m-%d"), "source": src, "total": t, "correct": int(c or 0)}
        for d, src, t, c in result.all()
    ]


async def record_chat_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    subject: str,
    grade: int | None,
    concepts: list,
) -> None:
    """Distill one answered tutor question into the durable day rollup.

    Runs inside the caller's transaction (no commit here). Race-safe: a single
    upsert, so two concurrent messages can't collide on the (user, day, subject)
    key the way read-then-insert would.
    """
    # Ethiopia is UTC+3 year-round (no DST), matching get_trends' bucketing.
    day = (datetime.now(timezone.utc) + timedelta(hours=3)).date()
    clean = [str(c)[:100] for c in concepts if c][:10]
    stmt = pg_insert(ChatActivity).values(
        user_id=user_id, day=day, subject=subject, grade=grade, count=1, concepts=clean,
    )
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["user_id", "day", "subject"],
        set_={
            "count": ChatActivity.count + 1,
            # jsonb || jsonb concatenates arrays; deduped/capped at read time.
            "concepts": ChatActivity.concepts.op("||")(stmt.excluded.concepts),
            "grade": stmt.excluded.grade,
        },
    ))


async def get_chat_context(db: AsyncSession, user_id: uuid.UUID, days: int = 7) -> list[dict]:
    """Per-subject tutor-chat volume + concepts asked about, last N days.

    Secondary analytics signal: shown only alongside accuracy-flagged weak
    areas, never as a struggle measure on its own.
    """
    since = ((datetime.now(timezone.utc) + timedelta(hours=3)) - timedelta(days=days)).date()
    result = await db.execute(
        select(ChatActivity.subject, func.sum(ChatActivity.count), func.jsonb_agg(ChatActivity.concepts))
        .where(ChatActivity.user_id == user_id, ChatActivity.day >= since)
        .group_by(ChatActivity.subject)
    )
    out = []
    for subject, count, concept_lists in result.all():
        seen: dict[str, None] = {}  # ordered dedupe, most-recent-day lists last
        for lst in (concept_lists or []):
            for c in (lst or []):
                seen.setdefault(c, None)
        out.append({"subject": subject, "count": int(count or 0), "concepts": list(seen)[:6]})
    out.sort(key=lambda r: -r["count"])
    return out


async def get_retention(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Per-subject Leitner-box strength from flashcard reviews.

    `strong` = cards in box 3+ (review interval ≥ 4 days) — a retention signal
    that complements accuracy: mastery measures the moment, this measures what
    has survived spaced repetition.
    """
    total = func.count()
    strong = func.sum(cast(FlashcardReview.box >= 3, Integer))
    result = await db.execute(
        select(FlashcardReview.subject, total.label("total"), strong.label("strong"))
        .where(FlashcardReview.user_id == user_id)
        .group_by(FlashcardReview.subject)
    )
    return [{"subject": s or "general", "total": t, "strong": int(st or 0)} for s, t, st in result.all()]


# ---------------------------------------------------------------------------
# Mistake bank (wrong-answered questions, re-served until mastered)
# ---------------------------------------------------------------------------

async def record_mistake(
    db: AsyncSession,
    user_id: uuid.UUID,
    source: str,
    subject: str | None,
    topic: str | None,
    question: dict,
) -> None:
    """Upsert a mistake keyed by question text; refresh last_seen_at on repeat."""
    key = srs.card_key(question.get("question", ""))
    await db.execute(
        pg_insert(Mistake)
        .values(user_id=user_id, card_key=key, source=source,
                subject=subject, topic=topic, question=question)
        .on_conflict_do_update(
            index_elements=["user_id", "card_key"],
            set_={"last_seen_at": datetime.now(timezone.utc), "question": question},
        )
    )
    await db.commit()


async def get_mistakes(
    db: AsyncSession,
    user_id: uuid.UUID,
    subject: str | None = None,
    limit: int = 20,
) -> list[Mistake]:
    conds = [Mistake.user_id == user_id]
    if subject:
        conds.append(Mistake.subject == subject)
    result = await db.execute(
        select(Mistake).where(*conds).order_by(Mistake.created_at).limit(limit)
    )
    return list(result.scalars().all())


async def count_mistakes(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (await db.execute(
        select(func.count()).select_from(Mistake).where(Mistake.user_id == user_id)
    )).scalar_one()


async def resolve_mistake(db: AsyncSession, user_id: uuid.UUID, front: str) -> bool:
    """Delete a mastered mistake. Returns True if a row was removed."""
    key = srs.card_key(front)
    result = await db.execute(
        Mistake.__table__.delete().where(
            Mistake.user_id == user_id, Mistake.card_key == key
        )
    )
    await db.commit()
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Bookmarks (user-starred questions, kept until unstarred)
# ---------------------------------------------------------------------------

async def add_bookmark(
    db: AsyncSession,
    user_id: uuid.UUID,
    source: str,
    subject: str | None,
    topic: str | None,
    question: dict,
) -> None:
    key = srs.card_key(question.get("question", ""))
    await db.execute(
        pg_insert(Bookmark)
        .values(user_id=user_id, card_key=key, source=source,
                subject=subject, topic=topic, question=question)
        .on_conflict_do_nothing(index_elements=["user_id", "card_key"])
    )
    await db.commit()


async def get_bookmarks(
    db: AsyncSession,
    user_id: uuid.UUID,
    subject: str | None = None,
    limit: int = 50,
) -> list[Bookmark]:
    conds = [Bookmark.user_id == user_id]
    if subject:
        conds.append(Bookmark.subject == subject)
    result = await db.execute(
        select(Bookmark).where(*conds).order_by(Bookmark.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def remove_bookmark(db: AsyncSession, user_id: uuid.UUID, front: str) -> bool:
    """Delete a bookmark by question text. Returns True if a row was removed."""
    key = srs.card_key(front)
    result = await db.execute(
        Bookmark.__table__.delete().where(
            Bookmark.user_id == user_id, Bookmark.card_key == key
        )
    )
    await db.commit()
    return result.rowcount > 0


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
