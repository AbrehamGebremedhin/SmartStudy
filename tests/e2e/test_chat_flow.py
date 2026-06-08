"""
E2E test: full chat session lifecycle.

Flow: create session → send messages → verify messages stored → update title →
      verify session detail → simulate expiry → session gone from list.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from tests.factories import create_chat_session
from tests.fixtures import FIXTURE_CHAT_RESPONSE


SESSION_PAYLOAD = {"subject": "physics", "grade": 11, "title": "New Chat"}


@pytest.mark.e2e
class TestChatSessionLifecycle:
    async def test_create_session_then_send_message(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.chat.run_chat_response",
            AsyncMock(return_value=FIXTURE_CHAT_RESPONSE),
        ):
            # 1. Create session
            create_resp = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
            assert create_resp.status_code == 201
            sid = create_resp.json()["id"]

            # 2. Send a message
            msg_resp = await client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"question": "What is Newton's second law?"},
            )
            assert msg_resp.status_code == 200
            body = msg_resp.json()
            assert body["current_response"]["response"] != ""
            assert body["session_id"] == sid

            # 3. Session detail shows both user + assistant messages
            detail_resp = await client.get(f"/api/chat/sessions/{sid}")
            messages = detail_resp.json()["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert messages[1]["role"] == "assistant"

    async def test_key_concepts_stored_in_assistant_message(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.chat.run_chat_response",
            AsyncMock(return_value=FIXTURE_CHAT_RESPONSE),
        ):
            cr = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
            sid = cr.json()["id"]
            await client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"question": "Explain F=ma"},
            )

        detail = await client.get(f"/api/chat/sessions/{sid}")
        assistant_msg = next(m for m in detail.json()["messages"] if m["role"] == "assistant")
        assert assistant_msg["key_concepts"] == ["force", "mass", "acceleration"]

    async def test_title_auto_updated_from_new_chat(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.chat.run_chat_response",
            AsyncMock(return_value=FIXTURE_CHAT_RESPONSE),
        ):
            cr = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
            sid = cr.json()["id"]
            msg_resp = await client.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"question": "Any question"},
            )

        assert msg_resp.json()["title"] == FIXTURE_CHAT_RESPONSE["title"]

        # Title change reflected in session list
        sessions = (await client.get("/api/chat/sessions")).json()
        session = next(s for s in sessions if s["id"] == sid)
        assert session["title"] == FIXTURE_CHAT_RESPONSE["title"]

    async def test_manual_title_update_persists(self, client: AsyncClient):
        cr = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
        sid = cr.json()["id"]
        await client.put(f"/api/chat/sessions/{sid}/title", json={"title": "My Custom Title"})
        detail = await client.get(f"/api/chat/sessions/{sid}")
        assert detail.json()["title"] == "My Custom Title"

    async def test_multiple_messages_in_sequence(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        with patch(
            "app.api.routes.chat.run_chat_response",
            AsyncMock(return_value=FIXTURE_CHAT_RESPONSE),
        ):
            cr = await client.post("/api/chat/sessions", json=SESSION_PAYLOAD)
            sid = cr.json()["id"]
            for question in ["First question?", "Second question?", "Third question?"]:
                await client.post(
                    f"/api/chat/sessions/{sid}/messages", json={"question": question}
                )

        detail = await client.get(f"/api/chat/sessions/{sid}")
        messages = detail.json()["messages"]
        # 3 user messages + 3 assistant replies
        assert len(messages) == 6

    async def test_expired_session_not_in_list(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        # Create an already-expired session directly in DB
        await create_chat_session(
            db_session,
            test_user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            title="Ghost Session",
        )
        await db_session.commit()

        sessions = (await client.get("/api/chat/sessions")).json()
        titles = [s["title"] for s in sessions]
        assert "Ghost Session" not in titles

    async def test_expired_session_not_retrievable_by_id(
        self, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        expired = await create_chat_session(
            db_session,
            test_user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await db_session.commit()
        resp = await client.get(f"/api/chat/sessions/{expired.id}")
        assert resp.status_code == 404
