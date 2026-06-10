"""
Unit tests for topic-aware context retrieval in GenerationAgent.generate_mcqs().

Mocks the context_agent so no DB or LLM calls are made.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "agents"))


@pytest.fixture
def agent():
    with (
        patch("GenerationAgent.ContextRefinementAgent"),
        patch("GenerationAgent.ValidationAgent"),
        patch("GenerationAgent.SessionManager"),
        patch("GenerationAgent.ChatDeepSeek"),
    ):
        from GenerationAgent import GenerationAgent
        instance = GenerationAgent.__new__(GenerationAgent)
        instance.logger = MagicMock()
        instance.context_agent = MagicMock()
        instance.validation_agent = MagicMock()
        instance._retrieve_mcq_context = AsyncMock()
        return instance


@pytest.mark.asyncio
async def test_topic_calls_query_db_directly(agent):
    mock_context = MagicMock()
    mock_context.error = None
    mock_context.context = []
    mock_context.parsed_answer = {"areas": []}
    agent.context_agent.query_db = AsyncMock(return_value=mock_context)
    agent.validation_agent.validate_mcqs = AsyncMock(
        return_value={"needs_replacement": False, "valid_mcqs": [], "invalid_indices": []}
    )

    with patch("GenerationAgent.get_subject_rules", return_value=""), \
         patch("GenerationAgent.get_mcq_subject_guidance", return_value=""), \
         patch("GenerationAgent.get_grounding_rule", return_value=""), \
         patch("GenerationAgent.format_docs", return_value=""), \
         patch("GenerationAgent.PromptTemplate") as mock_pt, \
         patch("GenerationAgent.StrOutputParser"):
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(return_value='{"questions": []}')
        mock_pt.from_template.return_value.__or__ = MagicMock(return_value=mock_chain)

        await agent.generate_mcqs(
            subject="biology", grade=None, unit=None,
            topic="Photosynthesis", num_questions=1, difficulty="medium"
        )

    agent.context_agent.query_db.assert_awaited_once()
    call_kwargs = agent.context_agent.query_db.call_args.kwargs
    assert call_kwargs["grade"] is None
    assert call_kwargs["unit"] is None
    assert "Photosynthesis" in call_kwargs["question"]
    agent._retrieve_mcq_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_topic_calls_retrieve_mcq_context(agent):
    mock_context = MagicMock()
    mock_context.error = None
    mock_context.context = []
    mock_context.parsed_answer = {"areas": []}
    agent._retrieve_mcq_context = AsyncMock(return_value=mock_context)
    agent.validation_agent.validate_mcqs = AsyncMock(
        return_value={"needs_replacement": False, "valid_mcqs": [], "invalid_indices": []}
    )

    with patch("GenerationAgent.get_subject_rules", return_value=""), \
         patch("GenerationAgent.get_mcq_subject_guidance", return_value=""), \
         patch("GenerationAgent.get_grounding_rule", return_value=""), \
         patch("GenerationAgent.format_docs", return_value=""), \
         patch("GenerationAgent.PromptTemplate") as mock_pt, \
         patch("GenerationAgent.StrOutputParser"):
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(return_value='{"questions": []}')
        mock_pt.from_template.return_value.__or__ = MagicMock(return_value=mock_chain)

        await agent.generate_mcqs(
            subject="biology", grade=11, unit="2",
            topic=None, num_questions=1, difficulty="medium"
        )

    agent._retrieve_mcq_context.assert_awaited_once_with("biology", 11, "2", "medium")
    agent.context_agent.query_db.assert_not_called()


@pytest.mark.asyncio
async def test_topic_query_string_contains_difficulty(agent):
    mock_context = MagicMock()
    mock_context.error = None
    mock_context.context = []
    mock_context.parsed_answer = {"areas": []}
    agent.context_agent.query_db = AsyncMock(return_value=mock_context)
    agent.validation_agent.validate_mcqs = AsyncMock(
        return_value={"needs_replacement": False, "valid_mcqs": [], "invalid_indices": []}
    )

    with patch("GenerationAgent.get_subject_rules", return_value=""), \
         patch("GenerationAgent.get_mcq_subject_guidance", return_value=""), \
         patch("GenerationAgent.get_grounding_rule", return_value=""), \
         patch("GenerationAgent.format_docs", return_value=""), \
         patch("GenerationAgent.PromptTemplate") as mock_pt, \
         patch("GenerationAgent.StrOutputParser"):
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(return_value='{"questions": []}')
        mock_pt.from_template.return_value.__or__ = MagicMock(return_value=mock_chain)

        await agent.generate_mcqs(
            subject="chemistry", grade=None, unit=None,
            topic="Periodic Table", num_questions=1, difficulty="hard"
        )

    question_arg = agent.context_agent.query_db.call_args.kwargs["question"]
    assert "hard" in question_arg
    assert "Periodic Table" in question_arg
