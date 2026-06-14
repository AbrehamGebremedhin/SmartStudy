"""
Integration tests for WebSocket generation endpoints:
  /api/ws/generate/notes
  /api/ws/generate/mcq
  /api/ws/generate/flashcards

Uses starlette.testclient.TestClient (sync WS context manager) rather than
AsyncClient because pytest-asyncio's running event loop conflicts with
TestClient's internal anyio portal when opened inside an async coroutine.

Auth:  _auth_ws is patched to return a fake User — no JWT or DB user lookup.
DB:    crud helpers are patched individually; the injected session is an
       AsyncMock so await session.commit() resolves cleanly.
LLM:   generation service functions are patched with fixture payloads.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient  # used only in ws_app fixture

pytestmark = pytest.mark.filterwarnings("ignore::starlette.testclient.StarletteDeprecationWarning")

from app.db.database import get_db
from app.db.models import User
from app.main import app
from tests.fixtures import (
    FIXTURE_FLASHCARD_RESPONSE,
    FIXTURE_MCQ_RESPONSE,
    FIXTURE_NOTES_RESPONSE,
)

# ── Shared payloads ──────────────────────────────────────────────────────────

NOTES_PAYLOAD = {
    "subject": "physics",
    "topic": "Newton's Laws",
    "grade": 11,
    "unit": "1",
    "version": "1.0",
}

MCQ_PAYLOAD = {
    "subject": "physics",
    "grade": 11,
    "unit": "1",
    "num_questions": 2,
    "difficulty": "medium",
}

FLASHCARD_PAYLOAD = {
    "subject": "physics",
    "grade": 11,
    "unit": "1",
    "num_cards": 2,
    "difficulty": "medium",
}

# ── Helpers ──────────────────────────────────────────────────────────────────


def _fake_user() -> User:
    u = User(google_id="google-ws-test", email="ws-test@example.com")
    u.id = uuid.uuid4()
    return u


def _fake_generation(content: dict) -> MagicMock:
    gen = MagicMock()
    gen.id = uuid.uuid4()
    gen.content = content
    return gen


def _collect(ws, *, until=("result", "error"), limit=20) -> list[dict]:
    """Drain messages from *ws* until a terminal type or *limit* messages."""
    msgs = []
    for _ in range(limit):
        msg = ws.receive_json()
        msgs.append(msg)
        if msg.get("type") in until:
            break
    return msgs


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def ws_app(reset_rate_limiter):  # noqa: PT004 – reset_rate_limiter is autouse-like
    """
    Yield a TestClient with get_db overridden to a mock async session.
    Individual tests patch _auth_ws and crud calls as needed.
    """
    mock_session = AsyncMock()

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db
    yield TestClient(app), mock_session
    app.dependency_overrides.pop(get_db, None)


# ── Notes WS tests ───────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWsGenerateNotes:
    def test_progress_messages_flow_to_result(self, ws_app):
        client, mock_session = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({"notes": FIXTURE_NOTES_RESPONSE["notes"]})

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_notes", AsyncMock(return_value=FIXTURE_NOTES_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        types = [m["type"] for m in msgs]
        assert "progress" in types
        assert types[-1] == "result"

    def test_all_five_stages_emitted(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({"notes": FIXTURE_NOTES_RESPONSE["notes"]})

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_notes", AsyncMock(return_value=FIXTURE_NOTES_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        progress = [m for m in msgs if m["type"] == "progress"]
        stages = [m["stage"] for m in progress]
        assert stages == ["validating", "cache_check", "loading_context", "generating", "saving"]

    def test_stage_index_increments(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({"notes": FIXTURE_NOTES_RESPONSE["notes"]})

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_notes", AsyncMock(return_value=FIXTURE_NOTES_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        indices = [m["stage_index"] for m in msgs if m["type"] == "progress"]
        assert indices == list(range(len(indices)))

    def test_result_contains_notes_and_generation_id(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({"notes": FIXTURE_NOTES_RESPONSE["notes"]})

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_notes", AsyncMock(return_value=FIXTURE_NOTES_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        result = next(m for m in msgs if m["type"] == "result")
        assert result["data"]["generation_id"] == str(fake_gen.id)
        assert result["data"]["was_cache_hit"] is False
        assert "notes" in result["data"]

    def test_cache_hit_skips_generation_and_loading_context(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        cached_gen = _fake_generation({"notes": FIXTURE_NOTES_RESPONSE["notes"]})

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=cached_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_notes", AsyncMock()) as mock_gen,
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        mock_gen.assert_not_called()
        result = next(m for m in msgs if m["type"] == "result")
        assert result["data"]["was_cache_hit"] is True
        assert result["data"]["generation_id"] == str(cached_gen.id)

    def test_auth_failure_closes_connection(self, ws_app):
        # Patch verify_app_token so the real _auth_ws runs and calls websocket.close(4001).
        # If we mock _auth_ws entirely it skips the close call and receive_json() hangs.
        client, _ = ws_app

        with patch(
            "app.api.routes.ws.verify_app_token",
            AsyncMock(side_effect=Exception("invalid token")),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=bad-token") as ws:
                with pytest.raises(Exception):
                    ws.receive_json()

    def test_agent_error_sends_error_message(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch(
                "app.api.routes.ws.run_generate_notes",
                AsyncMock(return_value={"error": "topic_not_in_unit", "message": "Topic not found."}),
            ),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        error = next(m for m in msgs if m["type"] == "error")
        assert error["code"] == "topic_not_in_unit"

    def test_invalid_subject_sends_error(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()

        with patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json({**NOTES_PAYLOAD, "subject": "alchemy"})
                msgs = _collect(ws)

        assert any(m["type"] == "error" for m in msgs)

    def test_missing_token_query_param_closes_with_422(self, ws_app):
        # No token= query param → FastAPI rejects the WS upgrade before accept()
        client, _ = ws_app
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws/generate/notes") as ws:
                ws.receive_json()

    def test_out_of_context_grade_sends_error(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()

        with patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json({**NOTES_PAYLOAD, "grade": 9, "unit": "99"})
                msgs = _collect(ws)

        # out_of_context error from curriculum validation
        assert any(m["type"] == "error" for m in msgs)


# ── MCQ WS tests ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWsGenerateMCQ:
    def test_progress_messages_flow_to_result(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "questions": FIXTURE_MCQ_RESPONSE["questions"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_mcqs", AsyncMock(return_value=FIXTURE_MCQ_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/mcq?token=test-token") as ws:
                ws.send_json(MCQ_PAYLOAD)
                msgs = _collect(ws)

        types = [m["type"] for m in msgs]
        assert "progress" in types
        assert types[-1] == "result"

    def test_result_contains_questions(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "questions": FIXTURE_MCQ_RESPONSE["questions"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_mcqs", AsyncMock(return_value=FIXTURE_MCQ_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/mcq?token=test-token") as ws:
                ws.send_json(MCQ_PAYLOAD)
                msgs = _collect(ws)

        result = next(m for m in msgs if m["type"] == "result")
        assert "questions" in result["data"]
        assert result["data"]["was_cache_hit"] is False

    def test_result_is_always_freshly_generated(self, ws_app):
        """Generic requests always generate fresh — no pure cache hits."""
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "questions": FIXTURE_MCQ_RESPONSE["questions"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_mcqs", AsyncMock(return_value=FIXTURE_MCQ_RESPONSE)) as mock_gen,
        ):
            with client.websocket_connect("/api/ws/generate/mcq?token=test-token") as ws:
                ws.send_json(MCQ_PAYLOAD)
                msgs = _collect(ws)

        mock_gen.assert_called_once()
        result = next(m for m in msgs if m["type"] == "result")
        assert result["data"]["was_cache_hit"] is False

    def test_generating_stage_label_includes_count(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "questions": FIXTURE_MCQ_RESPONSE["questions"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_mcqs", AsyncMock(return_value=FIXTURE_MCQ_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/mcq?token=test-token") as ws:
                ws.send_json(MCQ_PAYLOAD)
                msgs = _collect(ws)

        gen_stage = next(m for m in msgs if m.get("stage") == "generating")
        # MCQ_PAYLOAD has num_questions=2, empty pool → fresh_count=2
        assert "2" in gen_stage["label"]

    def test_agent_error_sends_error_message(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch(
                "app.api.routes.ws.run_generate_mcqs",
                AsyncMock(return_value={"error": "No relevant documents found"}),
            ),
        ):
            with client.websocket_connect("/api/ws/generate/mcq?token=test-token") as ws:
                ws.send_json(MCQ_PAYLOAD)
                msgs = _collect(ws)

        assert any(m["type"] == "error" for m in msgs)


# ── Flashcard WS tests ───────────────────────────────────────────────────────


@pytest.mark.integration
class TestWsGenerateFlashcards:
    def test_progress_messages_flow_to_result(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "flashcards": FIXTURE_FLASHCARD_RESPONSE["flashcards"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_flashcards", AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/flashcards?token=test-token") as ws:
                ws.send_json(FLASHCARD_PAYLOAD)
                msgs = _collect(ws)

        types = [m["type"] for m in msgs]
        assert "progress" in types
        assert types[-1] == "result"

    def test_result_contains_flashcards(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "flashcards": FIXTURE_FLASHCARD_RESPONSE["flashcards"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_flashcards", AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/flashcards?token=test-token") as ws:
                ws.send_json(FLASHCARD_PAYLOAD)
                msgs = _collect(ws)

        result = next(m for m in msgs if m["type"] == "result")
        assert "flashcards" in result["data"]
        assert "difficulty" in result["data"]

    def test_result_is_always_freshly_generated(self, ws_app):
        """Generic requests always generate fresh — no pure cache hits."""
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "flashcards": FIXTURE_FLASHCARD_RESPONSE["flashcards"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_flashcards", AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE)) as mock_gen,
        ):
            with client.websocket_connect("/api/ws/generate/flashcards?token=test-token") as ws:
                ws.send_json(FLASHCARD_PAYLOAD)
                msgs = _collect(ws)

        mock_gen.assert_called_once()
        result = next(m for m in msgs if m["type"] == "result")
        assert result["data"]["was_cache_hit"] is False

    def test_generating_stage_label_includes_count(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({
            "flashcards": FIXTURE_FLASHCARD_RESPONSE["flashcards"],
            "difficulty": "medium",
        })

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_pooled_items", AsyncMock(return_value=[])),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_flashcards", AsyncMock(return_value=FIXTURE_FLASHCARD_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/flashcards?token=test-token") as ws:
                ws.send_json(FLASHCARD_PAYLOAD)
                msgs = _collect(ws)

        gen_stage = next(m for m in msgs if m.get("stage") == "generating")
        # FLASHCARD_PAYLOAD has num_cards=2, empty pool → fresh_count=2
        assert "2" in gen_stage["label"]

    def test_auth_failure_closes_connection(self, ws_app):
        client, _ = ws_app

        with patch(
            "app.api.routes.ws.verify_app_token",
            AsyncMock(side_effect=Exception("invalid token")),
        ):
            with client.websocket_connect("/api/ws/generate/flashcards?token=bad") as ws:
                with pytest.raises(Exception):
                    ws.receive_json()


# ── Protocol-level tests (endpoint-agnostic) ─────────────────────────────────


@pytest.mark.integration
class TestWsProtocol:
    def test_progress_messages_have_required_fields(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({"notes": FIXTURE_NOTES_RESPONSE["notes"]})

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_notes", AsyncMock(return_value=FIXTURE_NOTES_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        for msg in msgs:
            if msg["type"] == "progress":
                assert "stage" in msg
                assert "stage_index" in msg
                assert "total_stages" in msg
                assert "label" in msg
                assert isinstance(msg["stage_index"], int)
                assert msg["total_stages"] == 5

    def test_result_message_has_required_fields(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()
        fake_gen = _fake_generation({"notes": FIXTURE_NOTES_RESPONSE["notes"]})

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch("app.api.routes.ws.crud.save_generation", AsyncMock(return_value=fake_gen)),
            patch("app.api.routes.ws.crud.link_user_generation", AsyncMock()),
            patch("app.api.routes.ws.run_generate_notes", AsyncMock(return_value=FIXTURE_NOTES_RESPONSE)),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        result = next(m for m in msgs if m["type"] == "result")
        assert "data" in result
        assert "generation_id" in result["data"]
        assert "was_cache_hit" in result["data"]

    def test_error_message_has_code_and_detail(self, ws_app):
        client, _ = ws_app
        fake_user = _fake_user()

        with (
            patch("app.api.routes.ws._auth_ws", AsyncMock(return_value=fake_user)),
            patch("app.api.routes.ws.crud.get_cached_generation", AsyncMock(return_value=None)),
            patch(
                "app.api.routes.ws.run_generate_notes",
                AsyncMock(return_value={"error": "some_error_code", "message": "Something went wrong."}),
            ),
        ):
            with client.websocket_connect("/api/ws/generate/notes?token=test-token") as ws:
                ws.send_json(NOTES_PAYLOAD)
                msgs = _collect(ws)

        error = next(m for m in msgs if m["type"] == "error")
        assert "code" in error
        assert "detail" in error
