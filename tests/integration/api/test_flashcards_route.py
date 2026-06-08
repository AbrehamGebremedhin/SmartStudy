"""
Integration tests for POST /api/flashcards/generate.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.fixtures import FIXTURE_FLASHCARD_RESPONSE


@pytest.fixture
def mock_run_generate_flashcards():
    with patch("app.api.routes.flashcards.run_generate_flashcards", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_FLASHCARD_RESPONSE
        yield m


FC_PAYLOAD = {
    "subject": "physics",
    "grade": 11,
    "unit": "1",
    "topic": None,
    "num_cards": 1,
    "difficulty": "medium",
}


@pytest.mark.integration
class TestGenerateFlashcardsSuccess:
    async def test_returns_200_with_flashcards(self, client: AsyncClient, mock_run_generate_flashcards):
        resp = await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert "flashcards" in body
        assert isinstance(body["flashcards"], list)

    async def test_response_has_required_fields(self, client: AsyncClient, mock_run_generate_flashcards):
        resp = await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
        body = resp.json()
        assert "generation_id" in body
        assert "was_cache_hit" in body
        assert "difficulty" in body

    async def test_first_request_is_not_cache_hit(self, client: AsyncClient, mock_run_generate_flashcards):
        resp = await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
        assert resp.json()["was_cache_hit"] is False


@pytest.mark.integration
class TestGenerateFlashcardsCache:
    async def test_identical_request_is_cache_hit(self, client: AsyncClient, mock_run_generate_flashcards):
        await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
        resp2 = await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
        assert resp2.json()["was_cache_hit"] is True

    async def test_different_topic_misses_cache(self, client: AsyncClient, mock_run_generate_flashcards):
        await client.post("/api/flashcards/generate", json={**FC_PAYLOAD, "topic": "kinematics"})
        await client.post("/api/flashcards/generate", json={**FC_PAYLOAD, "topic": "dynamics"})
        assert mock_run_generate_flashcards.call_count == 2


@pytest.mark.integration
class TestGenerateFlashcardsValidation:
    async def test_num_cards_zero_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/flashcards/generate", json={**FC_PAYLOAD, "num_cards": 0})
        assert resp.status_code == 422

    async def test_num_cards_over_max_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/flashcards/generate", json={**FC_PAYLOAD, "num_cards": 21})
        assert resp.status_code == 422

    async def test_missing_subject_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/flashcards/generate", json={"grade": 11})
        assert resp.status_code == 422


@pytest.mark.integration
class TestGenerateFlashcardsAuth:
    async def test_unauthenticated_returns_401_or_403(self, unauth_client: AsyncClient):
        resp = await unauth_client.post("/api/flashcards/generate", json=FC_PAYLOAD)
        assert resp.status_code in (401, 403)


@pytest.mark.integration
class TestGenerateFlashcardsAgentError:
    async def test_agent_error_returns_422(self, client: AsyncClient):
        with patch(
            "app.api.routes.flashcards.run_generate_flashcards",
            AsyncMock(return_value={"error": "Generation failed"}),
        ):
            resp = await client.post("/api/flashcards/generate", json=FC_PAYLOAD)
        assert resp.status_code == 422
