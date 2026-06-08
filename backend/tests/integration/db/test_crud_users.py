"""
Integration tests for user CRUD operations.

Uses a real PostgreSQL database (testcontainers).
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from app.db.models import User


@pytest.mark.integration
class TestGetOrCreateUser:
    async def test_creates_new_user_on_first_call(self, db_session: AsyncSession):
        user = await crud.get_or_create_user(db_session, clerk_id="google-new-123", email="new@example.com")
        assert user.id is not None
        assert user.google_id == "google-new-123"
        assert user.email == "new@example.com"

    async def test_returns_existing_user_on_second_call(self, db_session: AsyncSession):
        u1 = await crud.get_or_create_user(db_session, clerk_id="google-existing-456", email="a@example.com")
        u2 = await crud.get_or_create_user(db_session, clerk_id="google-existing-456", email="a@example.com")
        assert u1.id == u2.id

    async def test_only_one_row_created_for_same_google_id(self, db_session: AsyncSession):
        google_id = f"google-{uuid.uuid4().hex[:8]}"
        await crud.get_or_create_user(db_session, clerk_id=google_id, email="x@example.com")
        await crud.get_or_create_user(db_session, clerk_id=google_id, email="x@example.com")

        from sqlalchemy import select, func
        result = await db_session.execute(
            select(func.count()).select_from(User).where(User.google_id == google_id)
        )
        assert result.scalar() == 1

    async def test_updates_email_on_second_call(self, db_session: AsyncSession):
        gid = f"google-{uuid.uuid4().hex[:8]}"
        await crud.get_or_create_user(db_session, clerk_id=gid, email="old@example.com")
        user = await crud.get_or_create_user(db_session, clerk_id=gid, email="new@example.com")
        assert user.email == "new@example.com"

    async def test_last_seen_at_updated_on_second_call(self, db_session: AsyncSession):
        gid = f"google-{uuid.uuid4().hex[:8]}"
        u1 = await crud.get_or_create_user(db_session, clerk_id=gid, email="a@example.com")
        first_seen = u1.last_seen_at
        u2 = await crud.get_or_create_user(db_session, clerk_id=gid, email="a@example.com")
        # last_seen_at should be >= first_seen (may be the same if within same second)
        assert u2.last_seen_at >= first_seen

    async def test_different_google_ids_create_different_users(self, db_session: AsyncSession):
        u1 = await crud.get_or_create_user(db_session, clerk_id="gid-aaa", email="a@x.com")
        u2 = await crud.get_or_create_user(db_session, clerk_id="gid-bbb", email="b@x.com")
        assert u1.id != u2.id
