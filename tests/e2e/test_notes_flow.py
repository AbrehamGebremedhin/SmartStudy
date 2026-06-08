"""
E2E test: full notes generation flow.

Flow: generate notes → verify structure → cache → history.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from tests.fixtures import FIXTURE_NOTES_RESPONSE


NOTES_PAYLOAD = {
    "subject": "physics",
    "topic": "Newton's Laws of Motion",
    "grade": 11,
    "unit": "1",
    "version": "1.0",
}


@pytest.mark.e2e
class TestNotesGenerationFlow:
    async def test_full_generation_and_cache_flow(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.notes.run_generate_notes",
            AsyncMock(return_value=FIXTURE_NOTES_RESPONSE),
        ) as mock_agent:
            # 1. First request → fresh generation
            resp1 = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
            assert resp1.status_code == 200
            body1 = resp1.json()
            assert body1["was_cache_hit"] is False
            assert "notes" in body1
            gen_id = body1["generation_id"]

            # 2. Agent called once
            assert mock_agent.call_count == 1

            # 3. Cache hit
            resp2 = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
            assert resp2.json()["was_cache_hit"] is True
            assert resp2.json()["generation_id"] == gen_id
            assert mock_agent.call_count == 1

        # 4. History entry present
        rows = await crud.get_user_history(db_session, test_user.id, generation_type="notes")
        assert len(rows) == 2

    async def test_notes_structure_contains_expected_keys(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.notes.run_generate_notes",
            AsyncMock(return_value=FIXTURE_NOTES_RESPONSE),
        ):
            resp = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)

        notes = resp.json()["notes"]
        assert "title" in notes
        assert "overview" in notes
        assert "key_concepts" in notes
        assert "sections" in notes

    async def test_notes_persisted_as_jsonb(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.notes.run_generate_notes",
            AsyncMock(return_value=FIXTURE_NOTES_RESPONSE),
        ):
            await client.post("/api/notes/generate", json=NOTES_PAYLOAD)

        rows = await crud.get_user_history(db_session, test_user.id, generation_type="notes")
        _, gen = rows[0]
        stored_notes = gen.content["notes"]
        assert stored_notes["title"] == "Newton's Laws of Motion"
