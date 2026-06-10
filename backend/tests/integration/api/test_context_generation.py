"""
Integration tests for cross-feature generation:
  - MCQ / flashcard generated from a note (note_id)
  - MCQ / flashcard / notes generated from a chat session (chat_session_id)
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    create_chat_message,
    create_chat_session,
    create_notes_generation,
    create_user,
    create_user_generation,
)
from tests.fixtures import FIXTURE_FLASHCARD_RESPONSE, FIXTURE_MCQ_RESPONSE, FIXTURE_NOTES_RESPONSE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mcq():
    with patch("app.api.routes.mcq.run_generate_mcqs", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_MCQ_RESPONSE
        yield m


@pytest.fixture
def mock_flashcards():
    with patch("app.api.routes.flashcards.run_generate_flashcards", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_FLASHCARD_RESPONSE
        yield m


@pytest.fixture
def mock_notes():
    with patch("app.api.routes.notes.run_generate_notes", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_NOTES_RESPONSE
        yield m


# ---------------------------------------------------------------------------
# MCQ from note
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMCQFromNote:
    async def test_note_id_passes_note_content_to_agent(
        self, client: AsyncClient, mock_mcq, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        resp = await client.post("/api/mcq/generate", json={
            "subject": "physics", "num_questions": 1, "difficulty": "medium",
            "note_id": str(gen.id),
        })
        assert resp.status_code == 200
        kwargs = mock_mcq.call_args.kwargs
        assert kwargs["note_content"] is not None

    async def test_unknown_note_id_returns_404(
        self, client: AsyncClient, mock_mcq
    ):
        resp = await client.post("/api/mcq/generate", json={
            "subject": "physics", "num_questions": 1, "difficulty": "medium",
            "note_id": str(uuid.uuid4()),
        })
        assert resp.status_code == 404

    async def test_other_users_note_returns_404(
        self, client: AsyncClient, mock_mcq, db_session: AsyncSession
    ):
        other = await create_user(db_session)
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, other.id, gen.id)
        await db_session.commit()

        resp = await client.post("/api/mcq/generate", json={
            "subject": "physics", "num_questions": 1, "difficulty": "medium",
            "note_id": str(gen.id),
        })
        assert resp.status_code == 404

    async def test_note_id_and_no_note_id_cache_separately(
        self, client: AsyncClient, mock_mcq, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        base = {"subject": "physics", "num_questions": 1, "difficulty": "medium"}
        await client.post("/api/mcq/generate", json=base)
        await client.post("/api/mcq/generate", json={**base, "note_id": str(gen.id)})
        assert mock_mcq.call_count == 2


# ---------------------------------------------------------------------------
# Flashcard from note
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFlashcardFromNote:
    async def test_note_id_passes_note_content_to_agent(
        self, client: AsyncClient, mock_flashcards, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        resp = await client.post("/api/flashcards/generate", json={
            "subject": "physics", "num_cards": 1, "difficulty": "medium",
            "note_id": str(gen.id),
        })
        assert resp.status_code == 200
        kwargs = mock_flashcards.call_args.kwargs
        assert kwargs["note_content"] is not None

    async def test_unknown_note_id_returns_404(self, client: AsyncClient, mock_flashcards):
        resp = await client.post("/api/flashcards/generate", json={
            "subject": "physics", "num_cards": 1, "difficulty": "medium",
            "note_id": str(uuid.uuid4()),
        })
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# MCQ from chat session
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMCQFromChat:
    async def test_chat_session_id_passes_chat_context_to_agent(
        self, client: AsyncClient, mock_mcq, test_user, db_session: AsyncSession
    ):
        session = await create_chat_session(db_session, test_user.id)
        await create_chat_message(db_session, session.id, role="user", content="Tell me about Newton's laws")
        await create_chat_message(db_session, session.id, role="assistant",
                                  content="Newton's laws describe motion.", key_concepts=["Newton's laws"])
        await db_session.commit()

        resp = await client.post("/api/mcq/generate", json={
            "subject": "physics", "num_questions": 1, "difficulty": "medium",
            "chat_session_id": str(session.id),
        })
        assert resp.status_code == 200
        kwargs = mock_mcq.call_args.kwargs
        assert kwargs["chat_context"] is not None
        assert "Newton's laws" in kwargs["chat_context"]

    async def test_unknown_chat_session_returns_404(self, client: AsyncClient, mock_mcq):
        resp = await client.post("/api/mcq/generate", json={
            "subject": "physics", "num_questions": 1, "difficulty": "medium",
            "chat_session_id": str(uuid.uuid4()),
        })
        assert resp.status_code == 404

    async def test_other_users_session_returns_404(
        self, client: AsyncClient, mock_mcq, db_session: AsyncSession
    ):
        other = await create_user(db_session)
        session = await create_chat_session(db_session, other.id)
        await db_session.commit()

        resp = await client.post("/api/mcq/generate", json={
            "subject": "physics", "num_questions": 1, "difficulty": "medium",
            "chat_session_id": str(session.id),
        })
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Flashcard from chat session
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFlashcardFromChat:
    async def test_chat_session_id_passes_chat_context_to_agent(
        self, client: AsyncClient, mock_flashcards, test_user, db_session: AsyncSession
    ):
        session = await create_chat_session(db_session, test_user.id)
        await create_chat_message(db_session, session.id, role="assistant",
                                  content="Photosynthesis converts light to energy.",
                                  key_concepts=["photosynthesis"])
        await db_session.commit()

        resp = await client.post("/api/flashcards/generate", json={
            "subject": "biology", "num_cards": 1, "difficulty": "easy",
            "chat_session_id": str(session.id),
        })
        assert resp.status_code == 200
        kwargs = mock_flashcards.call_args.kwargs
        assert kwargs["chat_context"] is not None


# ---------------------------------------------------------------------------
# Notes from chat session
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestNotesFromChat:
    async def test_chat_session_id_passes_chat_context_to_agent(
        self, client: AsyncClient, mock_notes, test_user, db_session: AsyncSession
    ):
        session = await create_chat_session(db_session, test_user.id, subject="biology")
        await create_chat_message(db_session, session.id, role="assistant",
                                  content="Chlorophyll absorbs light in photosynthesis.",
                                  key_concepts=["chlorophyll", "photosynthesis"])
        await db_session.commit()

        resp = await client.post("/api/notes/generate", json={
            "subject": "biology", "topic": "Photosynthesis",
            "chat_session_id": str(session.id),
        })
        assert resp.status_code == 200
        kwargs = mock_notes.call_args.kwargs
        assert kwargs["chat_context"] is not None
        assert "chlorophyll" in kwargs["chat_context"].lower()

    async def test_unknown_chat_session_returns_404(self, client: AsyncClient, mock_notes):
        resp = await client.post("/api/notes/generate", json={
            "subject": "biology", "topic": "Photosynthesis",
            "chat_session_id": str(uuid.uuid4()),
        })
        assert resp.status_code == 404
