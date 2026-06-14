"""
E2E test: full flashcard generation flow.

Flow: generate flashcards → verify response → cache hit on repeat → history.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from tests.fixtures import FIXTURE_FLASHCARD_RESPONSE


FC_PAYLOAD = {
    "subject": "biology",
    "grade": 10,
    "unit": "2",
    "topic": "Cell Division",
    "num_cards": 1,
    "difficulty": "medium",
}


@pytest.mark.e2e
class TestFlashcardGenerationFlow:
    async def test_full_generation_and_cache_flow(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.flashcards.run_generate_flashcards",
            AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE),
        ) as mock_agent:
            # 1. First request → fresh generation
            resp1 = await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
            assert resp1.status_code == 200
            body1 = resp1.json()
            assert body1["was_cache_hit"] is False
            assert len(body1["flashcards"]) >= 1
            gen_id = body1["generation_id"]

            # 2. Agent called once
            assert mock_agent.call_count == 1

            # 3. Second identical request: pool + fresh (no pure cache hit)
            resp2 = await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
            assert resp2.json()["was_cache_hit"] is False
            assert resp2.json()["generation_id"] != gen_id  # new generation saved
            assert mock_agent.call_count == 2  # agent called again for fresh items

        # 4. History reflects both entries (both fresh generations)
        rows = await crud.get_user_history(db_session, test_user.id, generation_type="flashcard")
        assert len(rows) == 2

    async def test_flashcard_content_persisted_correctly(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.flashcards.run_generate_flashcards",
            AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE),
        ):
            await client.post("/api/flashcards/generate", json=FC_PAYLOAD)

        rows = await crud.get_user_history(db_session, test_user.id, generation_type="flashcard")
        _, gen = rows[0]
        flashcards = gen.content["flashcards"]
        assert len(flashcards) >= 1
        assert "front" in flashcards[0]
        assert "back" in flashcards[0]

    async def test_flashcard_token_usage_persisted(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.flashcards.run_generate_flashcards",
            AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE),
        ):
            await client.post("/api/flashcards/generate", json=FC_PAYLOAD)

        rows = await crud.get_user_history(db_session, test_user.id, generation_type="flashcard")
        _, gen = rows[0]
        assert gen.input_tokens > 0
        assert gen.output_tokens > 0
