"""
Helper factory functions for creating test DB rows.
These are plain async functions (not factory_boy) to keep async SQLAlchemy simple.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession, Generation, User, UserGeneration


async def create_user(db: AsyncSession, **kwargs) -> User:
    user = User(
        google_id=kwargs.get("google_id", f"google-{uuid.uuid4().hex[:8]}"),
        email=kwargs.get("email", "factory-user@example.com"),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def create_generation(db: AsyncSession, **kwargs) -> Generation:
    gen = Generation(
        type=kwargs.get("type", "mcq"),
        request_hash=kwargs.get("request_hash", uuid.uuid4().hex),
        request_params=kwargs.get(
            "request_params",
            {"subject": "physics", "grade": 11, "unit": "1", "num_questions": 5, "difficulty": "medium"},
        ),
        content=kwargs.get(
            "content",
            {
                "questions": [
                    {
                        "topic": "Kinematics",
                        "question": "What is velocity?",
                        "options": ["A) Rate of change of displacement", "B) Speed only", "C) Distance/time", "D) None"],
                        "correct_answer": "A",
                        "passage": None,
                        "workout_steps": [],
                        "correct_explanations": ["Velocity is displacement per unit time"],
                        "incorrect_explanations": {"B": "wrong", "C": "wrong", "D": "wrong"},
                    }
                ],
                "difficulty": "medium",
            },
        ),
        input_tokens=kwargs.get("input_tokens", 500),
        output_tokens=kwargs.get("output_tokens", 1200),
        cost_usd=kwargs.get("cost_usd", 0.000454),
    )
    db.add(gen)
    await db.flush()
    await db.refresh(gen)
    return gen


async def create_flashcard_generation(db: AsyncSession, **kwargs) -> Generation:
    return await create_generation(
        db,
        type="flashcard",
        request_params=kwargs.get(
            "request_params",
            {"subject": "physics", "grade": 11, "unit": "1", "topic": None, "num_cards": 5, "difficulty": "medium"},
        ),
        content=kwargs.get(
            "content",
            {
                "flashcards": [
                    {"topic": "Kinematics", "front": "What is velocity?", "back": "Rate of change of displacement"}
                ],
                "difficulty": "medium",
            },
        ),
        **{k: v for k, v in kwargs.items() if k not in ("type", "request_params", "content")},
    )


async def create_notes_generation(db: AsyncSession, **kwargs) -> Generation:
    return await create_generation(
        db,
        type="notes",
        request_params=kwargs.get(
            "request_params",
            {"subject": "physics", "topic": "Kinematics", "grade": 11, "unit": "1", "version": "1.0"},
        ),
        content=kwargs.get(
            "content",
            {
                "notes": {
                    "title": "Kinematics",
                    "overview": "Study of motion without forces.",
                    "key_concepts": ["velocity", "acceleration"],
                }
            },
        ),
        **{k: v for k, v in kwargs.items() if k not in ("type", "request_params", "content")},
    )


async def create_user_generation(
    db: AsyncSession,
    user_id: uuid.UUID,
    generation_id: uuid.UUID,
    **kwargs,
) -> UserGeneration:
    ug = UserGeneration(
        user_id=user_id,
        generation_id=generation_id,
        was_cache_hit=kwargs.get("was_cache_hit", False),
    )
    db.add(ug)
    await db.flush()
    await db.refresh(ug)
    return ug


async def create_chat_session(db: AsyncSession, user_id: uuid.UUID, **kwargs) -> ChatSession:
    expires_at = kwargs.get("expires_at", datetime.now(timezone.utc) + timedelta(hours=24))
    session = ChatSession(
        user_id=user_id,
        subject=kwargs.get("subject", "physics"),
        grade=kwargs.get("grade", 11),
        title=kwargs.get("title", "Test Session"),
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def create_chat_message(db: AsyncSession, session_id: uuid.UUID, **kwargs) -> ChatMessage:
    message = ChatMessage(
        session_id=session_id,
        role=kwargs.get("role", "user"),
        content=kwargs.get("content", "Test question"),
        key_concepts=kwargs.get("key_concepts", []),
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message
