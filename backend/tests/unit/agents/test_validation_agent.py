"""
Unit tests for ValidationAgent — structural checks only (no LLM call).

The LLM-driven validation path is tested by patching _run_chain so that
we control the LLM output. Structural checks (option count, duplicate
questions, missing keys) need no mocking at all.
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "agents"))

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent():
    """ValidationAgent with the LLM constructor mocked out."""
    with patch("ValidationAgent.ChatDeepSeek"), patch("utils.tiktoken") as mock_tiktoken:
        mock_tiktoken.encoding_for_model.return_value.encode.return_value = [0] * 10
        from ValidationAgent import ValidationAgent as VA
        return VA()


def _valid_mcq(question: str = "What is F = ma?") -> dict:
    return {
        "topic": "Newton's Laws",
        "question": question,
        "options": ["A) Force", "B) Mass", "C) Acceleration", "D) Velocity"],
        "correct_answer": "A",
        "passage": None,
        "workout_steps": [],
        "correct_explanations": ["F = ma is Newton's second law"],
        "incorrect_explanations": {"B": "wrong", "C": "wrong", "D": "wrong"},
    }


def _valid_flashcard(front: str = "What is F = ma?") -> dict:
    return {"topic": "Newton's Laws", "front": front, "back": "Force = mass × acceleration"}


# ---------------------------------------------------------------------------
# validate_mcqs — structural checks (no LLM call)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateMcqsStructural:
    async def test_empty_list_returns_valid(self, agent):
        result = await agent.validate_mcqs([], context="ctx")
        assert result["valid_mcqs"] == []
        assert result["needs_replacement"] is False

    async def test_valid_mcq_passes_structural_check(self, agent):
        mcqs = [_valid_mcq()]
        # Mock LLM call to approve all
        valid_response = json.dumps({"results": [{"index": 0, "is_valid": True, "reason": ""}]})
        with patch.object(agent, "_run_chain", AsyncMock(return_value=valid_response)):
            result = await agent.validate_mcqs(mcqs, context="ctx")
        assert len(result["valid_mcqs"]) == 1
        assert result["needs_replacement"] is False

    async def test_mcq_missing_required_key_is_invalid(self, agent):
        mcq = _valid_mcq()
        del mcq["correct_explanations"]
        result = await agent.validate_mcqs([mcq], context="ctx")
        assert len(result["valid_mcqs"]) == 0
        assert result["needs_replacement"] is True

    async def test_mcq_with_wrong_option_count_is_invalid(self, agent):
        mcq = _valid_mcq()
        mcq["options"] = ["A) only", "B) two", "C) three"]  # 3 options instead of 4
        result = await agent.validate_mcqs([mcq], context="ctx")
        assert len(result["valid_mcqs"]) == 0

    async def test_duplicate_question_text_is_invalid(self, agent):
        mcq1 = _valid_mcq("Duplicate question?")
        mcq2 = _valid_mcq("Duplicate question?")
        # Second is a structural duplicate
        result = await agent.validate_mcqs([mcq1, mcq2], context="ctx")
        # Only the first should survive structural check
        assert len(result["valid_mcqs"]) <= 1

    async def test_missing_incorrect_explanation_for_option(self, agent):
        mcq = _valid_mcq()
        # Remove explanation for option B — it's listed in options but not in incorrect_explanations
        del mcq["incorrect_explanations"]["B"]
        result = await agent.validate_mcqs([mcq], context="ctx")
        assert len(result["valid_mcqs"]) == 0

    async def test_llm_rejection_removes_mcq(self, agent):
        mcqs = [_valid_mcq()]
        reject_response = json.dumps({"results": [{"index": 0, "is_valid": False, "reason": "off-topic"}]})
        with patch.object(agent, "_run_chain", AsyncMock(return_value=reject_response)):
            result = await agent.validate_mcqs(mcqs, context="ctx")
        assert len(result["valid_mcqs"]) == 0
        assert result["needs_replacement"] is True

    async def test_llm_failure_keeps_candidates_valid(self, agent):
        mcqs = [_valid_mcq()]
        with patch.object(agent, "_run_chain", AsyncMock(side_effect=Exception("LLM error"))):
            result = await agent.validate_mcqs(mcqs, context="ctx")
        # On batch failure, keep all structurally valid candidates
        assert len(result["valid_mcqs"]) == 1


# ---------------------------------------------------------------------------
# validate_flashcards — structural checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateFlashcardsStructural:
    async def test_empty_list(self, agent):
        result = await agent.validate_flashcards([], context="ctx")
        assert result["valid_flashcards"] == []
        assert result["needs_replacement"] is False

    async def test_valid_flashcard_passes(self, agent):
        cards = [_valid_flashcard()]
        valid_response = json.dumps({"results": [{"index": 0, "is_valid": True, "reason": ""}]})
        with patch.object(agent, "_run_chain", AsyncMock(return_value=valid_response)):
            result = await agent.validate_flashcards(cards, context="ctx")
        assert len(result["valid_flashcards"]) == 1

    async def test_duplicate_front_text_is_invalid(self, agent):
        card1 = _valid_flashcard("What is velocity?")
        card2 = _valid_flashcard("What is velocity?")
        result = await agent.validate_flashcards([card1, card2], context="ctx")
        assert len(result["valid_flashcards"]) <= 1

    async def test_missing_front_key_is_invalid(self, agent):
        card = {"topic": "Physics", "back": "Some answer"}  # missing front
        result = await agent.validate_flashcards([card], context="ctx")
        assert len(result["valid_flashcards"]) == 0

    async def test_missing_back_key_is_invalid(self, agent):
        card = {"topic": "Physics", "front": "What is velocity?"}  # missing back
        result = await agent.validate_flashcards([card], context="ctx")
        assert len(result["valid_flashcards"]) == 0


# ---------------------------------------------------------------------------
# validate_chat_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateChatResponse:
    async def test_error_response_is_invalid(self, agent):
        result = await agent.validate_chat_response(
            {"error": "LLM failed"}, context="ctx", keypoints=[]
        )
        assert result["is_valid"] is False
        assert result["needs_regeneration"] is True

    async def test_empty_response_text_is_invalid(self, agent):
        result = await agent.validate_chat_response(
            {"response": "  "}, context="ctx", keypoints=[]
        )
        assert result["is_valid"] is False

    async def test_valid_response_passes(self, agent):
        valid_llm = json.dumps({"is_valid": True, "reason": ""})
        with patch.object(agent, "_run_chain", AsyncMock(return_value=valid_llm)):
            result = await agent.validate_chat_response(
                {"response": "Newton's second law is F=ma."},
                context="ctx",
                keypoints=["force"],
            )
        assert result["is_valid"] is True

    async def test_llm_failure_assumes_valid(self, agent):
        with patch.object(agent, "_run_chain", AsyncMock(side_effect=Exception("fail"))):
            result = await agent.validate_chat_response(
                {"response": "Some response"}, context="ctx", keypoints=[]
            )
        assert result["is_valid"] is True
        assert result["needs_regeneration"] is False
