"""
Integration tests for POST /api/mcq/generate.

GenerationAgent and ContextRefinementAgent are mocked; DB and HTTP layers are real.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from tests.factories import create_generation, create_user_generation
from tests.fixtures import FIXTURE_MCQ_RESPONSE


@pytest.fixture
def mock_run_generate_mcqs():
    with patch("app.api.routes.mcq.run_generate_mcqs", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_MCQ_RESPONSE
        yield m


MCQ_PAYLOAD = {
    "subject": "physics",
    "grade": 11,
    "unit": "1",
    "num_questions": 1,
    "difficulty": "medium",
}


@pytest.mark.integration
class TestGenerateMcqSuccess:
    async def test_returns_200_with_questions(self, client: AsyncClient, mock_run_generate_mcqs):
        resp = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert "questions" in body
        assert isinstance(body["questions"], list)
        assert len(body["questions"]) >= 1

    async def test_response_has_required_fields(self, client: AsyncClient, mock_run_generate_mcqs):
        resp = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        body = resp.json()
        assert "generation_id" in body
        assert "was_cache_hit" in body
        assert "difficulty" in body

    async def test_first_request_not_cache_hit(self, client: AsyncClient, mock_run_generate_mcqs):
        resp = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        assert resp.json()["was_cache_hit"] is False

    async def test_agent_called_on_cache_miss(self, client: AsyncClient, mock_run_generate_mcqs):
        await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        mock_run_generate_mcqs.assert_called_once()


@pytest.mark.integration
class TestGenerateMcqCache:
    async def test_second_identical_request_is_cache_hit(
        self, client: AsyncClient, mock_run_generate_mcqs
    ):
        await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        resp2 = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        assert resp2.json()["was_cache_hit"] is True

    async def test_cache_hit_does_not_call_agent_again(
        self, client: AsyncClient, mock_run_generate_mcqs
    ):
        await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        # Agent should only be called once (first request)
        assert mock_run_generate_mcqs.call_count == 1

    async def test_different_params_call_agent_twice(
        self, client: AsyncClient, mock_run_generate_mcqs
    ):
        await client.post("/api/mcq/generate", json={**MCQ_PAYLOAD, "grade": 11})
        await client.post("/api/mcq/generate", json={**MCQ_PAYLOAD, "grade": 12})
        assert mock_run_generate_mcqs.call_count == 2


@pytest.mark.integration
class TestGenerateMcqValidation:
    async def test_invalid_num_questions_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/mcq/generate", json={**MCQ_PAYLOAD, "num_questions": 0})
        assert resp.status_code == 422

    async def test_num_questions_exceeds_max_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/mcq/generate", json={**MCQ_PAYLOAD, "num_questions": 21})
        assert resp.status_code == 422

    async def test_invalid_difficulty_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/mcq/generate", json={**MCQ_PAYLOAD, "difficulty": "extreme"})
        assert resp.status_code == 422

    async def test_missing_subject_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/mcq/generate", json={"grade": 11, "num_questions": 5})
        assert resp.status_code == 422


@pytest.mark.integration
class TestGenerateMcqAuth:
    async def test_unauthenticated_request_returns_403_or_401(self, unauth_client: AsyncClient):
        resp = await unauth_client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        assert resp.status_code in (401, 403)


@pytest.mark.integration
class TestGenerateMcqHistory:
    async def test_generation_appears_in_history_after_request(
        self, client: AsyncClient, mock_run_generate_mcqs, test_user, db_session: AsyncSession
    ):
        await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        rows = await crud.get_user_history(db_session, test_user.id, generation_type="mcq")
        assert len(rows) >= 1
        _, gen = rows[0]
        assert gen.type == "mcq"


@pytest.mark.integration
class TestGenerateMcqAgentError:
    async def test_agent_error_returns_422(self, client: AsyncClient):
        with patch(
            "app.api.routes.mcq.run_generate_mcqs",
            AsyncMock(return_value={"error": "LLM failed to generate"}),
        ):
            resp = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
        assert resp.status_code == 422
