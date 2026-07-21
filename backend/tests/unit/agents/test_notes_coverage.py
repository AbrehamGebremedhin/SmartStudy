"""
Unit test for the notes coverage/generation overlap in agents/notes.py.

The coverage check now runs concurrently with generation instead of gating it: on a
'not covered' result the in-flight generation must be cancelled and the topic_not_in_unit
error returned (not swallowed into a generic failure, and without waiting out the whole
generation). This guards that new control-flow branch.
"""
import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "agents"))

from models import TokenCount  # noqa: E402
from notes import NotesMixin  # noqa: E402


class _Agent(NotesMixin):
    """Minimal host for NotesMixin.generate_notes with faked collaborators."""

    def __init__(self, coverage: dict, gen_started: asyncio.Event, gen_cancelled: list):
        self.logger = logging.getLogger("test-notes")
        self.context_agent = SimpleNamespace(
            query_documents_only=AsyncMock(return_value=SimpleNamespace(
                error=None,
                context=[Document(page_content="Grade 11 physics content about motion.")],
                parsed_answer={},
            ))
        )

        async def _coverage(**_):
            await asyncio.sleep(0.05)  # yield so generation actually starts first (overlap)
            return coverage

        self.validation_agent = SimpleNamespace(
            validate_coverage_from_context=_coverage
        )

        async def _slow_gen(_):
            gen_started.set()
            try:
                await asyncio.sleep(30)  # still running when coverage resolves
            except asyncio.CancelledError:
                gen_cancelled.append(True)
                raise
            return '{"title": "x"}'

        self._json_llm = RunnableLambda(_slow_gen)

    def _record_token_usage(self, a, b):  # not reached on the not-covered path
        return TokenCount(0, 0, 0.0)


@pytest.mark.unit
class TestNotesCoverageOverlap:
    async def test_not_covered_cancels_generation_and_returns_error(self):
        gen_started = asyncio.Event()
        gen_cancelled: list = []
        agent = _Agent(
            coverage={"is_covered": False, "available_topics": ["Kinematics", "Forces"]},
            gen_started=gen_started,
            gen_cancelled=gen_cancelled,
        )

        result = await asyncio.wait_for(
            agent.generate_notes(subject="physics", topic="Nonexistent Topic",
                                 grade=11, unit="1"),
            timeout=5,  # must return promptly, NOT wait out the 30s generation
        )

        assert result["error"] == "topic_not_in_unit"
        assert "Nonexistent Topic" in result["message"]
        assert result["available_topics"] == ["Kinematics", "Forces"]
        assert gen_started.is_set()       # generation was actually kicked off (overlap)
        assert len(gen_cancelled) == 3    # all parallel calls (core+applied+extra) cancelled
