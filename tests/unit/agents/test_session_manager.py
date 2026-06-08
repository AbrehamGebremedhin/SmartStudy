"""
Unit tests for app/agents/session_manager.py.

No I/O, no DB, no LLM.
"""
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "agents"))

import pytest

from session_manager import SessionManager


@pytest.fixture
def manager():
    return SessionManager(ttl_hours=1)


@pytest.mark.unit
class TestSessionManagerCreate:
    def test_returns_non_empty_id(self, manager):
        sid = manager.create("physics")
        assert sid and isinstance(sid, str)

    def test_two_sessions_have_unique_ids(self, manager):
        sid1 = manager.create("physics")
        sid2 = manager.create("chemistry")
        assert sid1 != sid2

    def test_session_retrievable_after_create(self, manager):
        sid = manager.create("biology", title="Test Session", grade=10)
        session = manager.get(sid)
        assert session is not None
        assert session.subject == "biology"
        assert session.title == "Test Session"
        assert session.grade == 10

    def test_default_title_is_new_chat(self, manager):
        sid = manager.create("maths")
        assert manager.get(sid).title == "New Chat"

    def test_grade_defaults_to_none(self, manager):
        sid = manager.create("history")
        assert manager.get(sid).grade is None


@pytest.mark.unit
class TestSessionManagerGet:
    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get("nonexistent-id") is None

    def test_expired_session_cleaned_on_next_create(self):
        mgr = SessionManager(ttl_hours=1)
        sid = mgr.create("physics")
        # Backdate created_at to 2 hours ago to simulate TTL expiry
        mgr.get(sid).created_at = datetime.now() - timedelta(hours=2)
        # Next create triggers _cleanup_expired which should remove the stale session
        mgr.create("trigger-cleanup")
        assert mgr.get(sid) is None


@pytest.mark.unit
class TestSessionManagerUpdateTitle:
    def test_update_existing_session_title(self, manager):
        sid = manager.create("physics")
        result = manager.update_title(sid, "New Title")
        assert result is True
        assert manager.get(sid).title == "New Title"

    def test_update_nonexistent_session_returns_false(self, manager):
        assert manager.update_title("bad-id", "Title") is False


@pytest.mark.unit
class TestSessionManagerTTL:
    def test_session_not_expired_before_ttl(self):
        mgr = SessionManager(ttl_hours=1)
        sid = mgr.create("physics")
        # Session was just created — it should still be alive
        mgr.create("trigger")  # triggers cleanup (cutoff = now - 1h, session < 1s old)
        assert mgr.get(sid) is not None

    def test_session_expired_after_ttl(self):
        mgr = SessionManager(ttl_hours=1)
        sid = mgr.create("physics")
        # Backdate created_at to 2 hours ago to simulate expiry
        mgr.get(sid).created_at = datetime.now() - timedelta(hours=2)
        mgr.create("trigger")  # triggers _cleanup_expired
        assert mgr.get(sid) is None

    def test_zero_ttl_never_expires(self):
        mgr = SessionManager(ttl_hours=0)
        sid = mgr.create("physics")
        # Backdate created_at to the distant past
        mgr.get(sid).created_at = datetime.now() - timedelta(days=365 * 10)
        mgr.create("trigger")  # _cleanup_expired returns early when ttl_hours <= 0
        assert mgr.get(sid) is not None


@pytest.mark.unit
class TestSessionManagerThreadSafety:
    def test_concurrent_creates_produce_unique_ids(self):
        mgr = SessionManager(ttl_hours=24)
        ids = []
        errors = []

        def create_session():
            try:
                ids.append(mgr.create("physics"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_session) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(set(ids)) == 50  # all unique
