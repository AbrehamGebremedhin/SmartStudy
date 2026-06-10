"""
Integration tests for POST /api/notes/{generation_id}/chat.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import create_notes_generation, create_user_generation
from tests.fixtures import FIXTURE_NOTE_CHAT_RESPONSE


@pytest.fixture
def mock_run_note_chat():
    with patch("app.api.routes.notes.run_note_chat", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_NOTE_CHAT_RESPONSE
        yield m


CHAT_PAYLOAD = {
    "question": "How is ATP produced during photosynthesis?",
    "chat_history": [],
}


@pytest.mark.integration
class TestNoteChatSuccess:
    async def test_returns_200_with_answer(
        self, client: AsyncClient, mock_run_note_chat, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        resp = await client.post(f"/api/notes/{gen.id}/chat", json=CHAT_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert "answer" in body
        assert "key_concepts" in body
        assert "follow_up_questions" in body

    async def test_answer_is_non_empty(
        self, client: AsyncClient, mock_run_note_chat, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        resp = await client.post(f"/api/notes/{gen.id}/chat", json=CHAT_PAYLOAD)
        assert resp.json()["answer"] == FIXTURE_NOTE_CHAT_RESPONSE["answer"]

    async def test_agent_receives_question_and_subject(
        self, client: AsyncClient, mock_run_note_chat, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        await client.post(f"/api/notes/{gen.id}/chat", json=CHAT_PAYLOAD)
        mock_run_note_chat.assert_awaited_once()
        kwargs = mock_run_note_chat.call_args.kwargs
        assert kwargs["question"] == CHAT_PAYLOAD["question"]
        assert kwargs["subject"] == gen.request_params["subject"]

    async def test_chat_history_is_forwarded(
        self, client: AsyncClient, mock_run_note_chat, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        payload = {
            "question": "What else?",
            "chat_history": [
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
            ],
        }
        await client.post(f"/api/notes/{gen.id}/chat", json=payload)
        kwargs = mock_run_note_chat.call_args.kwargs
        assert "First question" in kwargs["chat_history_str"]
        assert "First answer" in kwargs["chat_history_str"]


@pytest.mark.integration
class TestNoteChatNotFound:
    async def test_unknown_generation_id_returns_404(
        self, client: AsyncClient, mock_run_note_chat
    ):
        resp = await client.post(f"/api/notes/{uuid.uuid4()}/chat", json=CHAT_PAYLOAD)
        assert resp.status_code == 404

    async def test_other_users_note_returns_404(
        self, client: AsyncClient, mock_run_note_chat, db_session: AsyncSession
    ):
        from tests.factories import create_user
        other_user = await create_user(db_session)
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, other_user.id, gen.id)
        await db_session.commit()

        resp = await client.post(f"/api/notes/{gen.id}/chat", json=CHAT_PAYLOAD)
        assert resp.status_code == 404


@pytest.mark.integration
class TestNoteChatValidation:
    async def test_empty_question_returns_422(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        resp = await client.post(f"/api/notes/{gen.id}/chat", json={"question": "", "chat_history": []})
        assert resp.status_code == 422

    async def test_missing_question_returns_422(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        gen = await create_notes_generation(db_session)
        await create_user_generation(db_session, test_user.id, gen.id)
        await db_session.commit()

        resp = await client.post(f"/api/notes/{gen.id}/chat", json={"chat_history": []})
        assert resp.status_code == 422


@pytest.mark.integration
class TestNoteChatAuth:
    async def test_unauthenticated_returns_401_or_403(self, unauth_client: AsyncClient):
        resp = await unauth_client.post(f"/api/notes/{uuid.uuid4()}/chat", json=CHAT_PAYLOAD)
        assert resp.status_code in (401, 403)
