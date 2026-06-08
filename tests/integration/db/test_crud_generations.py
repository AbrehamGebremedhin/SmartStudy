"""
Integration tests for Generation and UserGeneration CRUD operations.

Uses a real PostgreSQL database (testcontainers).
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from tests.factories import create_generation, create_user, create_user_generation


@pytest.mark.integration
class TestSaveAndRetrieveGeneration:
    async def test_save_generation_returns_row_with_id(self, db_session: AsyncSession):
        gen = await crud.save_generation(
            db_session,
            generation_type="mcq",
            request_hash="abc123",
            request_params={"subject": "physics"},
            content={"questions": [], "difficulty": "medium"},
            input_tokens=500,
            output_tokens=1200,
            cost_usd=0.0004,
        )
        assert gen.id is not None
        assert gen.type == "mcq"
        assert gen.request_hash == "abc123"

    async def test_content_stored_as_jsonb_round_trips(self, db_session: AsyncSession):
        complex_content = {
            "questions": [
                {
                    "topic": "Kinematics",
                    "question": "What is velocity?",
                    "options": ["A) Speed", "B) Acceleration", "C) Force", "D) Mass"],
                    "correct_answer": "A",
                    "nested": {"key": [1, 2, 3]},
                }
            ],
            "difficulty": "hard",
        }
        gen = await crud.save_generation(
            db_session,
            generation_type="mcq",
            request_hash=uuid.uuid4().hex,
            request_params={},
            content=complex_content,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )
        assert gen.content == complex_content

    async def test_cache_hit_returns_same_generation(self, db_session: AsyncSession):
        rh = uuid.uuid4().hex
        gen = await create_generation(db_session, request_hash=rh, type="mcq")
        cached = await crud.get_cached_generation(db_session, rh, "mcq")
        assert cached is not None
        assert cached.id == gen.id

    async def test_cache_miss_returns_none(self, db_session: AsyncSession):
        result = await crud.get_cached_generation(db_session, "nonexistent-hash", "mcq")
        assert result is None

    async def test_cache_type_mismatch_returns_none(self, db_session: AsyncSession):
        rh = uuid.uuid4().hex
        await create_generation(db_session, request_hash=rh, type="mcq")
        result = await crud.get_cached_generation(db_session, rh, "flashcard")
        assert result is None


@pytest.mark.integration
class TestLinkUserGeneration:
    async def test_link_creates_user_generation_row(self, db_session: AsyncSession):
        user = await create_user(db_session)
        gen = await create_generation(db_session)
        ug = await crud.link_user_generation(db_session, user.id, gen.id, was_cache_hit=False)
        assert ug.id is not None
        assert ug.user_id == user.id
        assert ug.generation_id == gen.id
        assert ug.was_cache_hit is False

    async def test_cache_hit_flag_stored(self, db_session: AsyncSession):
        user = await create_user(db_session)
        gen = await create_generation(db_session)
        ug = await crud.link_user_generation(db_session, user.id, gen.id, was_cache_hit=True)
        assert ug.was_cache_hit is True

    async def test_same_generation_linked_to_multiple_users(self, db_session: AsyncSession):
        u1 = await create_user(db_session)
        u2 = await create_user(db_session)
        gen = await create_generation(db_session)
        ug1 = await crud.link_user_generation(db_session, u1.id, gen.id, was_cache_hit=False)
        ug2 = await crud.link_user_generation(db_session, u2.id, gen.id, was_cache_hit=True)
        assert ug1.id != ug2.id
        assert ug1.generation_id == ug2.generation_id


@pytest.mark.integration
class TestGetUserHistory:
    async def test_returns_all_types_for_user(self, db_session: AsyncSession):
        user = await create_user(db_session)
        gen_mcq = await create_generation(db_session, type="mcq")
        gen_fc = await create_generation(db_session, type="flashcard")
        await crud.link_user_generation(db_session, user.id, gen_mcq.id, was_cache_hit=False)
        await crud.link_user_generation(db_session, user.id, gen_fc.id, was_cache_hit=False)
        await db_session.commit()

        rows = await crud.get_user_history(db_session, user.id)
        assert len(rows) == 2

    async def test_filtered_by_type(self, db_session: AsyncSession):
        user = await create_user(db_session)
        gen_mcq = await create_generation(db_session, type="mcq")
        gen_fc = await create_generation(db_session, type="flashcard")
        await crud.link_user_generation(db_session, user.id, gen_mcq.id, was_cache_hit=False)
        await crud.link_user_generation(db_session, user.id, gen_fc.id, was_cache_hit=False)
        await db_session.commit()

        rows = await crud.get_user_history(db_session, user.id, generation_type="mcq")
        assert len(rows) == 1
        _, gen = rows[0]
        assert gen.type == "mcq"

    async def test_empty_history_returns_empty_list(self, db_session: AsyncSession):
        user = await create_user(db_session)
        rows = await crud.get_user_history(db_session, user.id)
        assert rows == []

    async def test_pagination_limit(self, db_session: AsyncSession):
        user = await create_user(db_session)
        for _ in range(5):
            gen = await create_generation(db_session)
            await crud.link_user_generation(db_session, user.id, gen.id, was_cache_hit=False)
        await db_session.commit()

        rows = await crud.get_user_history(db_session, user.id, limit=3)
        assert len(rows) == 3

    async def test_pagination_offset(self, db_session: AsyncSession):
        user = await create_user(db_session)
        for _ in range(5):
            gen = await create_generation(db_session)
            await crud.link_user_generation(db_session, user.id, gen.id, was_cache_hit=False)
        await db_session.commit()

        all_rows = await crud.get_user_history(db_session, user.id)
        offset_rows = await crud.get_user_history(db_session, user.id, limit=50, offset=2)
        assert len(offset_rows) == len(all_rows) - 2

    async def test_history_isolated_per_user(self, db_session: AsyncSession):
        u1 = await create_user(db_session)
        u2 = await create_user(db_session)
        gen = await create_generation(db_session)
        await crud.link_user_generation(db_session, u1.id, gen.id, was_cache_hit=False)
        await db_session.commit()

        assert len(await crud.get_user_history(db_session, u1.id)) == 1
        assert len(await crud.get_user_history(db_session, u2.id)) == 0
