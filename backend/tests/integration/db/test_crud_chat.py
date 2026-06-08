"""
Integration tests for ChatSession and ChatMessage CRUD operations.

Uses a real PostgreSQL database (testcontainers).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from tests.factories import create_chat_message, create_chat_session, create_user


@pytest.mark.integration
class TestCreateChatSession:
    async def test_creates_session_with_correct_fields(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await crud.create_chat_session(
            db_session, user_id=user.id, subject="physics", grade=11, title="My Session"
        )
        assert session.id is not None
        assert session.subject == "physics"
        assert session.grade == 11
        assert session.title == "My Session"
        assert session.user_id == user.id

    async def test_session_has_future_expiry(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await crud.create_chat_session(
            db_session, user_id=user.id, subject="physics", grade=11, title="Test"
        )
        assert session.expires_at > datetime.now(timezone.utc)

    async def test_grade_can_be_none(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await crud.create_chat_session(
            db_session, user_id=user.id, subject="general", grade=None, title="No Grade"
        )
        assert session.grade is None


@pytest.mark.integration
class TestGetChatSession:
    async def test_retrieves_session_by_id_and_user(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(db_session, user.id)
        await db_session.commit()
        retrieved = await crud.get_chat_session(db_session, session.id, user.id)
        assert retrieved is not None
        assert retrieved.id == session.id

    async def test_wrong_user_returns_none(self, db_session: AsyncSession):
        user1 = await create_user(db_session)
        user2 = await create_user(db_session)
        session = await create_chat_session(db_session, user1.id)
        await db_session.commit()
        result = await crud.get_chat_session(db_session, session.id, user2.id)
        assert result is None

    async def test_nonexistent_session_returns_none(self, db_session: AsyncSession):
        user = await create_user(db_session)
        result = await crud.get_chat_session(db_session, uuid.uuid4(), user.id)
        assert result is None

    async def test_expired_session_returns_none(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(
            db_session, user.id, expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        await db_session.commit()
        result = await crud.get_chat_session(db_session, session.id, user.id)
        assert result is None


@pytest.mark.integration
class TestGetChatSessionWithMessages:
    async def test_returns_session_with_messages(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(db_session, user.id)
        await create_chat_message(db_session, session.id, role="user", content="Hello?")
        await create_chat_message(db_session, session.id, role="assistant", content="Hi there!")
        await db_session.commit()

        result = await crud.get_chat_session_with_messages(db_session, session.id, user.id)
        assert result is not None
        assert len(result.messages) == 2

    async def test_messages_ordered_by_timestamp(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(db_session, user.id)
        await create_chat_message(db_session, session.id, role="user", content="First")
        await create_chat_message(db_session, session.id, role="assistant", content="Second")
        await db_session.commit()

        result = await crud.get_chat_session_with_messages(db_session, session.id, user.id)
        roles = [m.role for m in result.messages]
        assert roles == ["user", "assistant"]


@pytest.mark.integration
class TestGetUserChatSessions:
    async def test_returns_only_active_sessions(self, db_session: AsyncSession):
        user = await create_user(db_session)
        active = await create_chat_session(db_session, user.id)
        await create_chat_session(
            db_session, user.id, expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        await db_session.commit()

        sessions = await crud.get_user_chat_sessions(db_session, user.id)
        assert len(sessions) == 1
        assert sessions[0].id == active.id

    async def test_returns_only_sessions_for_that_user(self, db_session: AsyncSession):
        u1 = await create_user(db_session)
        u2 = await create_user(db_session)
        await create_chat_session(db_session, u1.id)
        await create_chat_session(db_session, u1.id)
        await create_chat_session(db_session, u2.id)
        await db_session.commit()

        assert len(await crud.get_user_chat_sessions(db_session, u1.id)) == 2
        assert len(await crud.get_user_chat_sessions(db_session, u2.id)) == 1

    async def test_empty_for_new_user(self, db_session: AsyncSession):
        user = await create_user(db_session)
        assert await crud.get_user_chat_sessions(db_session, user.id) == []


@pytest.mark.integration
class TestUpdateChatSessionTitle:
    async def test_updates_title_successfully(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(db_session, user.id, title="Old Title")
        await db_session.commit()

        result = await crud.update_chat_session_title(db_session, session.id, user.id, "New Title")
        assert result is True

        updated = await crud.get_chat_session(db_session, session.id, user.id)
        assert updated.title == "New Title"

    async def test_update_nonexistent_returns_false(self, db_session: AsyncSession):
        user = await create_user(db_session)
        result = await crud.update_chat_session_title(db_session, uuid.uuid4(), user.id, "Title")
        assert result is False


@pytest.mark.integration
class TestAddChatMessage:
    async def test_adds_message_to_session(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(db_session, user.id)
        await db_session.commit()

        msg = await crud.add_chat_message(
            db_session, session.id, role="user", content="What is force?", key_concepts=[]
        )
        assert msg.id is not None
        assert msg.content == "What is force?"
        assert msg.role == "user"

    async def test_key_concepts_stored(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(db_session, user.id)
        await db_session.commit()

        msg = await crud.add_chat_message(
            db_session,
            session.id,
            role="assistant",
            content="Force = mass x acceleration",
            key_concepts=["force", "mass", "acceleration"],
        )
        assert msg.key_concepts == ["force", "mass", "acceleration"]

    async def test_adding_message_bumps_session_updated_at(self, db_session: AsyncSession):
        user = await create_user(db_session)
        session = await create_chat_session(db_session, user.id)
        original_updated_at = session.updated_at
        await db_session.commit()

        await crud.add_chat_message(
            db_session, session.id, role="user", content="Hello", key_concepts=[]
        )
        await db_session.refresh(session)
        assert session.updated_at >= original_updated_at
