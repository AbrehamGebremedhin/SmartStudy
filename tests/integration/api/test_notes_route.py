"""
Integration tests for POST /api/notes/generate.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.fixtures import FIXTURE_NOTES_RESPONSE


@pytest.fixture
def mock_run_generate_notes():
    with patch("app.api.routes.notes.run_generate_notes", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_NOTES_RESPONSE
        yield m


NOTES_PAYLOAD = {
    "subject": "physics",
    "topic": "Newton's Laws",
    "grade": 11,
    "unit": "1",
    "version": "1.0",
}


@pytest.mark.integration
class TestGenerateNotesSuccess:
    async def test_returns_200_with_notes(self, client: AsyncClient, mock_run_generate_notes):
        resp = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert "notes" in body
        assert isinstance(body["notes"], dict)

    async def test_response_has_required_fields(self, client: AsyncClient, mock_run_generate_notes):
        resp = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        body = resp.json()
        assert "generation_id" in body
        assert "was_cache_hit" in body

    async def test_first_request_not_cache_hit(self, client: AsyncClient, mock_run_generate_notes):
        resp = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        assert resp.json()["was_cache_hit"] is False

    async def test_notes_content_matches_fixture(self, client: AsyncClient, mock_run_generate_notes):
        resp = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        notes = resp.json()["notes"]
        assert notes.get("title") == "Newton's Laws of Motion"


@pytest.mark.integration
class TestGenerateNotesCache:
    async def test_identical_request_is_cache_hit(self, client: AsyncClient, mock_run_generate_notes):
        await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        resp2 = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        assert resp2.json()["was_cache_hit"] is True

    async def test_different_topic_misses_cache(self, client: AsyncClient, mock_run_generate_notes):
        await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        await client.post("/api/notes/generate", json={**NOTES_PAYLOAD, "topic": "Thermodynamics"})
        assert mock_run_generate_notes.call_count == 2


@pytest.mark.integration
class TestGenerateNotesValidation:
    async def test_missing_subject_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/notes/generate", json={"topic": "Newton"})
        assert resp.status_code == 422

    async def test_missing_topic_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/notes/generate", json={"subject": "physics"})
        assert resp.status_code == 422


@pytest.mark.integration
class TestGenerateNotesAuth:
    async def test_unauthenticated_returns_401_or_403(self, unauth_client: AsyncClient):
        resp = await unauth_client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        assert resp.status_code in (401, 403)


@pytest.mark.integration
class TestGenerateNotesAgentError:
    async def test_agent_error_returns_422(self, client: AsyncClient):
        with patch(
            "app.api.routes.notes.run_generate_notes",
            AsyncMock(return_value={"error": "Notes generation failed"}),
        ):
            resp = await client.post("/api/notes/generate", json=NOTES_PAYLOAD)
        assert resp.status_code == 422
