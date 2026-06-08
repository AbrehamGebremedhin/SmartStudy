"""
Integration tests for the chat session endpoints.

    POST   /api/chat/sessions
    GET    /api/chat/sessions
    GET    /api/chat/sessions/{id}
    PUT    /api/chat/sessions/{id}/title
    POST   /api/chat/sessions/{id}/messages
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import create_chat_session, create_user
from tests.fixtures import FIXTURE_CHAT_RESPONSE


@pytest.fixture
def mock_run_chat_response():
    with patch("app.api.routes.chat.run_chat_response", new_callable=AsyncMock) as m:
        m.return_value = FIXTURE_CHAT_RESPONSE
        yield m


SESSION_PAYLOAD = {"subject": "physics", "grade": 11, "title": "Physics Q&A"}


@pytest.mark.integration
class TestCreateSession:
    async def test_creates_session_returns_201(self, client: AsyncClient):
        resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        assert resp.status_code == 201

    async def test_response_has_session_fields(self, client: AsyncClient):
        resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        body = resp.json()
        assert "id" in body
        assert body["subject"] == "physics"
        assert body["grade"] == 11
        assert body["title"] == "Physics Q&A"

    async def test_unauthenticated_returns_401_or_403(self, unauth_client: AsyncClient):
        resp = await unauth_client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        assert resp.status_code in (401, 403)

    async def test_missing_subject_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/chat/sessions", json={"grade": 11})
        assert resp.status_code == 422


@pytest.mark.integration
class TestListSessions:
    async def test_empty_list_for_new_user(self, client: AsyncClient):
        resp = await client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_created_sessions(self, client: AsyncClient):
        await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        await client.post("/api/chat/sessions", json={**SESSION_PAYLOAD, "title": "Second"})
        resp = await client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_expired_session_excluded(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        # Create an already-expired session directly in DB
        await create_chat_session(
            db_session,
            test_user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await db_session.commit()
        resp = await client.get("/api/chat/sessions")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.integration
class TestGetSession:
    async def test_returns_session_detail(self, client: AsyncClient):
        create_resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        session_id = create_resp.json()["id"]
        resp = await client.get(f"/api/chat/sessions/{session_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == session_id
        assert "messages" in body

    async def test_nonexistent_session_returns_404(self, client: AsyncClient):
        resp = await client.get(f"/api/chat/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_other_users_session_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        other_user = await create_user(db_session)
        other_session = await create_chat_session(db_session, other_user.id)
        await db_session.commit()
        resp = await client.get(f"/api/chat/sessions/{other_session.id}")
        assert resp.status_code == 404


@pytest.mark.integration
class TestUpdateTitle:
    async def test_updates_title_returns_200(self, client: AsyncClient):
        create_resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        sid = create_resp.json()["id"]
        resp = await client.put(f"/api/chat/sessions/{sid}/title", json={"title": "Updated Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    async def test_nonexistent_session_returns_404(self, client: AsyncClient):
        resp = await client.put(
            f"/api/chat/sessions/{uuid.uuid4()}/title", json={"title": "X"}
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestSendMessage:
    async def test_sends_message_returns_reply(
        self, client: AsyncClient, mock_run_chat_response
    ):
        create_resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        sid = create_resp.json()["id"]
        resp = await client.post(
            f"/api/chat/sessions/{sid}/messages",
            json={"question": "What is Newton's second law?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "current_response" in body
        assert "session_id" in body

    async def test_reply_contains_response_text(
        self, client: AsyncClient, mock_run_chat_response
    ):
        create_resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        sid = create_resp.json()["id"]
        resp = await client.post(
            f"/api/chat/sessions/{sid}/messages",
            json={"question": "Explain F=ma"},
        )
        assert resp.json()["current_response"]["response"] != ""

    async def test_messages_stored_in_session_detail(
        self, client: AsyncClient, mock_run_chat_response
    ):
        create_resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        sid = create_resp.json()["id"]
        await client.post(
            f"/api/chat/sessions/{sid}/messages",
            json={"question": "What is inertia?"},
        )
        detail = await client.get(f"/api/chat/sessions/{sid}")
        messages = detail.json()["messages"]
        # user message + assistant reply
        assert len(messages) == 2
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    async def test_message_to_nonexistent_session_returns_404(
        self, client: AsyncClient, mock_run_chat_response
    ):
        resp = await client.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages",
            json={"question": "Hello?"},
        )
        assert resp.status_code == 404

    async def test_title_auto_updated_on_first_message(
        self, client: AsyncClient, mock_run_chat_response
    ):
        # Session starts as "New Chat"; the mock returns a suggested title
        create_resp = await client.post(
            "/api/chat/sessions", json={**SESSION_PAYLOAD, "title": "New Chat"}
        )
        sid = create_resp.json()["id"]
        resp = await client.post(
            f"/api/chat/sessions/{sid}/messages",
            json={"question": "Any question"},
        )
        assert resp.json()["title"] == FIXTURE_CHAT_RESPONSE["title"]
