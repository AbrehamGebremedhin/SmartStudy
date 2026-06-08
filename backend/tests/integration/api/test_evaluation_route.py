"""
Integration tests for POST /api/evaluate.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.fixtures import FIXTURE_EVAL_RESPONSE, FIXTURE_EVAL_RESPONSE_WRONG


EVAL_PAYLOAD = {
    "subject": "physics",
    "question": {
        "topic": "Newton's Laws",
        "question": "What is the acceleration of a 5 kg object under 10 N?",
        "options": ["A) 0.5 m/s^2", "B) 2 m/s^2", "C) 5 m/s^2", "D) 50 m/s^2"],
        "correct_answer": "B",
        "correct_explanations": ["a = F/m = 10/5 = 2 m/s^2"],
        "incorrect_explanations": {"A": "wrong", "C": "wrong", "D": "wrong"},
    },
    "student_answer": "The acceleration is 2 m/s^2 by F=ma.",
    "note": None,
}


@pytest.mark.integration
class TestEvaluateAnswerSuccess:
    async def test_returns_200_with_evaluation(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD)
        assert resp.status_code == 200

    async def test_response_has_all_fields(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD)
        body = resp.json()
        assert "is_correct" in body
        assert "score" in body
        assert "feedback" in body
        assert "improvement_suggestions" in body
        assert "correct_solution" in body
        assert "misconceptions" in body
        assert "key_points_missed" in body
        assert "strengths" in body

    async def test_correct_answer_returns_is_correct_true(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD)
        assert resp.json()["is_correct"] is True

    async def test_wrong_answer_returns_is_correct_false(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE_WRONG),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD)
        body = resp.json()
        assert body["is_correct"] is False
        assert len(body["misconceptions"]) > 0

    async def test_score_is_between_0_and_1(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD)
        score = resp.json()["score"]
        assert 0.0 <= score <= 1.0


@pytest.mark.integration
class TestEvaluateAnswerValidation:
    async def test_missing_subject_returns_422(self, client: AsyncClient):
        payload = {k: v for k, v in EVAL_PAYLOAD.items() if k != "subject"}
        resp = await client.post("/api/evaluate", json=payload)
        assert resp.status_code == 422

    async def test_missing_question_returns_422(self, client: AsyncClient):
        payload = {k: v for k, v in EVAL_PAYLOAD.items() if k != "question"}
        resp = await client.post("/api/evaluate", json=payload)
        assert resp.status_code == 422

    async def test_missing_student_answer_returns_422(self, client: AsyncClient):
        payload = {k: v for k, v in EVAL_PAYLOAD.items() if k != "student_answer"}
        resp = await client.post("/api/evaluate", json=payload)
        assert resp.status_code == 422


@pytest.mark.integration
class TestEvaluateAnswerAuth:
    async def test_unauthenticated_returns_401_or_403(self, unauth_client: AsyncClient):
        resp = await unauth_client.post("/api/evaluate", json=EVAL_PAYLOAD)
        assert resp.status_code in (401, 403)


@pytest.mark.integration
class TestEvaluateAnswerAgentError:
    async def test_agent_error_returns_422(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value={"error": "Evaluation failed"}),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD)
        assert resp.status_code == 422
