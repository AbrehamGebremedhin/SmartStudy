"""
E2E test: full MCQ generation flow.

Flow: authenticate → generate MCQs → verify response → check history →
      repeat same params → verify cache hit.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from tests.fixtures import FIXTURE_MCQ_RESPONSE


MCQ_PAYLOAD = {
    "subject": "physics",
    "grade": 11,
    "unit": "1",
    "num_questions": 1,
    "difficulty": "medium",
}


@pytest.mark.e2e
class TestMcqGenerationFlow:
    async def test_full_generation_and_cache_flow(
        self,
        client: AsyncClient,
        test_user,
        db_session: AsyncSession,
    ):
        with patch(
            "app.api.routes.mcq.run_generate_mcqs",
            AsyncMock(return_value=FIXTURE_MCQ_RESPONSE),
        ) as mock_agent:
            # 1. First request → fresh generation
            resp1 = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
            assert resp1.status_code == 200
            body1 = resp1.json()
            assert body1["was_cache_hit"] is False
            gen_id_1 = body1["generation_id"]

            # 2. Agent called once
            assert mock_agent.call_count == 1

            # 3. Response structure matches fixture
            assert body1["questions"][0]["topic"] == "Newton's Laws"
            assert body1["difficulty"] == "medium"

            # 4. Second identical request → cache hit
            resp2 = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
            assert resp2.status_code == 200
            body2 = resp2.json()
            assert body2["was_cache_hit"] is True

            # 5. Cache hit returns the same generation
            assert body2["generation_id"] == gen_id_1

            # 6. Agent NOT called again
            assert mock_agent.call_count == 1

        # 7. History shows two entries (one fresh, one cache hit) linked to same generation
        rows = await crud.get_user_history(db_session, test_user.id, generation_type="mcq")
        assert len(rows) == 2
        gen_ids = {str(gen.id) for _, gen in rows}
        assert gen_ids == {gen_id_1}

        cache_flags = {ug.was_cache_hit for ug, _ in rows}
        assert True in cache_flags
        assert False in cache_flags

    async def test_different_params_creates_separate_generation(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.mcq.run_generate_mcqs",
            AsyncMock(return_value=FIXTURE_MCQ_RESPONSE),
        ):
            await client.post("/api/mcq/generate", json={**MCQ_PAYLOAD, "grade": 11})
            await client.post("/api/mcq/generate", json={**MCQ_PAYLOAD, "grade": 12})

        rows = await crud.get_user_history(db_session, test_user.id, generation_type="mcq")
        gen_ids = {str(gen.id) for _, gen in rows}
        assert len(gen_ids) == 2  # Two distinct generation rows

    async def test_token_usage_stored_in_generation(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.mcq.run_generate_mcqs",
            AsyncMock(return_value=FIXTURE_MCQ_RESPONSE),
        ):
            await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)

        rows = await crud.get_user_history(db_session, test_user.id, generation_type="mcq")
        _, gen = rows[0]
        assert gen.input_tokens == 500
        assert gen.output_tokens == 1200
        assert gen.cost_usd > 0

    async def test_two_users_share_cached_generation(
        self,
        client: AsyncClient,
        test_user,
        db_session: AsyncSession,
    ):
        from app.api.deps import get_current_user
        from app.db.database import get_db
        from app.main import app
        from tests.factories import create_user

        user2 = await create_user(db_session)
        await db_session.commit()

        with patch(
            "app.api.routes.mcq.run_generate_mcqs",
            AsyncMock(return_value=FIXTURE_MCQ_RESPONSE),
        ) as mock_agent:
            # First user generates
            resp1 = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
            gen_id = resp1.json()["generation_id"]
            assert mock_agent.call_count == 1

            # Switch auth to user2 and make the same request
            async def _get_db2():
                yield db_session

            async def _get_user2():
                return user2

            app.dependency_overrides[get_db] = _get_db2
            app.dependency_overrides[get_current_user] = _get_user2

            resp2 = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
            assert resp2.json()["was_cache_hit"] is True
            assert resp2.json()["generation_id"] == gen_id
            # Agent still only called once (cache hit for user2)
            assert mock_agent.call_count == 1

        # Both users each have one history entry pointing to the same generation
        rows_u1 = await crud.get_user_history(db_session, test_user.id)
        rows_u2 = await crud.get_user_history(db_session, user2.id)
        assert len(rows_u1) == 1
        assert len(rows_u2) == 1
        assert str(rows_u1[0][1].id) == gen_id
        assert str(rows_u2[0][1].id) == gen_id
