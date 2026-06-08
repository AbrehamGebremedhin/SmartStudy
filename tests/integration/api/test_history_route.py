"""
Integration tests for the history endpoints.

    GET /api/history/{generation_type}
    GET /api/history/
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.fixtures import FIXTURE_FLASHCARD_RESPONSE, FIXTURE_MCQ_RESPONSE, FIXTURE_NOTES_RESPONSE


@pytest.fixture
def mock_agents():
    with (
        patch("app.api.routes.mcq.run_generate_mcqs", AsyncMock(return_value=FIXTURE_MCQ_RESPONSE)),
        patch(
            "app.api.routes.flashcards.run_generate_flashcards",
            AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE),
        ),
        patch(
            "app.api.routes.notes.run_generate_notes",
            AsyncMock(return_value=FIXTURE_NOTES_RESPONSE),
        ),
    ):
        yield


@pytest.mark.integration
class TestGetHistory:
    async def test_empty_history_for_new_user(self, client: AsyncClient):
        resp = await client.get("/api/history/")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_mcq_history_after_generation(
        self, client: AsyncClient, mock_agents
    ):
        await client.post(
            "/api/mcq/generate",
            json={"subject": "physics", "grade": 11, "num_questions": 1, "difficulty": "medium"},
        )
        resp = await client.get("/api/history/mcq")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["type"] == "mcq"

    async def test_history_filtered_by_type(self, client: AsyncClient, mock_agents):
        # Generate one MCQ and one flashcard
        await client.post(
            "/api/mcq/generate",
            json={"subject": "physics", "grade": 11, "num_questions": 1, "difficulty": "medium"},
        )
        await client.post(
            "/api/flashcards/generate",
            json={"subject": "physics", "grade": 11, "num_cards": 1, "difficulty": "medium"},
        )
        mcq_history = await client.get("/api/history/mcq")
        fc_history = await client.get("/api/history/flashcard")
        assert all(i["type"] == "mcq" for i in mcq_history.json())
        assert all(i["type"] == "flashcard" for i in fc_history.json())

    async def test_all_history_returns_all_types(self, client: AsyncClient, mock_agents):
        await client.post(
            "/api/mcq/generate",
            json={"subject": "physics", "grade": 11, "num_questions": 1, "difficulty": "medium"},
        )
        await client.post(
            "/api/flashcards/generate",
            json={"subject": "physics", "grade": 11, "num_cards": 1, "difficulty": "medium"},
        )
        resp = await client.get("/api/history/")
        assert len(resp.json()) == 2

    async def test_history_item_has_required_fields(self, client: AsyncClient, mock_agents):
        await client.post(
            "/api/mcq/generate",
            json={"subject": "physics", "grade": 11, "num_questions": 1, "difficulty": "medium"},
        )
        items = (await client.get("/api/history/mcq")).json()
        item = items[0]
        assert "user_generation_id" in item
        assert "generation_id" in item
        assert "type" in item
        assert "request_params" in item
        assert "was_cache_hit" in item
        assert "accessed_at" in item

    async def test_cache_hit_marked_correctly_in_history(self, client: AsyncClient, mock_agents):
        payload = {"subject": "physics", "grade": 11, "num_questions": 1, "difficulty": "medium"}
        await client.post("/api/mcq/generate", json=payload)
        await client.post("/api/mcq/generate", json=payload)  # cache hit
        items = (await client.get("/api/history/mcq")).json()
        # Sort by accessed_at; second item should be cache hit
        cache_flags = [i["was_cache_hit"] for i in items]
        assert False in cache_flags
        assert True in cache_flags

    async def test_unauthenticated_returns_401_or_403(self, unauth_client: AsyncClient):
        resp = await unauth_client.get("/api/history/mcq")
        assert resp.status_code in (401, 403)

    async def test_pagination_with_limit(self, client: AsyncClient, mock_agents):
        # Generate 3 MCQs with different params
        for grade in [9, 10, 11]:
            await client.post(
                "/api/mcq/generate",
                json={"subject": "physics", "grade": grade, "num_questions": 1, "difficulty": "medium"},
            )
        resp = await client.get("/api/history/mcq?limit=2")
        assert len(resp.json()) == 2

    async def test_invalid_generation_type_returns_422(self, client: AsyncClient):
        resp = await client.get("/api/history/invalid_type")
        assert resp.status_code == 422
