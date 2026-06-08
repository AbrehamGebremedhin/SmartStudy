"""
E2E test: full evaluation flow.

Flow: generate MCQs → pick a question → evaluate correct answer → evaluate wrong answer.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.fixtures import (
    FIXTURE_EVAL_RESPONSE,
    FIXTURE_EVAL_RESPONSE_WRONG,
    FIXTURE_MCQ_RESPONSE,
)


MCQ_PAYLOAD = {
    "subject": "physics",
    "grade": 11,
    "unit": "1",
    "num_questions": 1,
    "difficulty": "medium",
}

QUESTION_FROM_FIXTURE = FIXTURE_MCQ_RESPONSE["questions"][0]

EVAL_PAYLOAD_CORRECT = {
    "subject": "physics",
    "question": QUESTION_FROM_FIXTURE,
    "student_answer": "2 m/s^2, calculated using a = F/m = 10/5",
    "note": None,
}

EVAL_PAYLOAD_WRONG = {
    "subject": "physics",
    "question": QUESTION_FROM_FIXTURE,
    "student_answer": "50 m/s^2",
    "note": None,
}


@pytest.mark.e2e
class TestEvaluationFlow:
    async def test_generate_then_evaluate_correct_answer(self, client: AsyncClient):
        with (
            patch(
                "app.api.routes.mcq.run_generate_mcqs",
                AsyncMock(return_value=FIXTURE_MCQ_RESPONSE),
            ),
            patch(
                "app.api.routes.evaluation.run_evaluate_answer",
                AsyncMock(return_value=FIXTURE_EVAL_RESPONSE),
            ),
        ):
            # 1. Generate MCQs
            mcq_resp = await client.post("/api/mcq/generate", json=MCQ_PAYLOAD)
            assert mcq_resp.status_code == 200
            questions = mcq_resp.json()["questions"]
            assert len(questions) >= 1

            # 2. Evaluate a correct answer
            eval_resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD_CORRECT)
            assert eval_resp.status_code == 200
            body = eval_resp.json()
            assert body["is_correct"] is True
            assert body["score"] >= 0.8

    async def test_evaluate_wrong_answer_returns_misconceptions(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE_WRONG),
        ):
            eval_resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD_WRONG)
        assert eval_resp.status_code == 200
        body = eval_resp.json()
        assert body["is_correct"] is False
        assert len(body["misconceptions"]) > 0
        assert body["score"] < 0.5

    async def test_evaluation_response_structure(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD_CORRECT)

        body = resp.json()
        # All eight response fields must be present
        required_fields = [
            "is_correct", "score", "feedback",
            "improvement_suggestions", "correct_solution",
            "misconceptions", "key_points_missed", "strengths",
        ]
        for field in required_fields:
            assert field in body, f"Missing field: {field}"

    async def test_evaluation_with_note_passes_note_to_agent(self, client: AsyncClient):
        mock = AsyncMock(return_value=FIXTURE_EVAL_RESPONSE)
        with patch("app.api.routes.evaluation.run_evaluate_answer", mock):
            await client.post(
                "/api/evaluate",
                json={**EVAL_PAYLOAD_CORRECT, "note": "Student is in grade 11"},
            )
        # Agent should have been called with the note
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs.get("note") == "Student is in grade 11"

    async def test_correct_answer_has_non_empty_feedback(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD_CORRECT)
        assert resp.json()["feedback"] != ""

    async def test_wrong_answer_has_improvement_suggestions(self, client: AsyncClient):
        with patch(
            "app.api.routes.evaluation.run_evaluate_answer",
            AsyncMock(return_value=FIXTURE_EVAL_RESPONSE_WRONG),
        ):
            resp = await client.post("/api/evaluate", json=EVAL_PAYLOAD_WRONG)
        assert len(resp.json()["improvement_suggestions"]) > 0
