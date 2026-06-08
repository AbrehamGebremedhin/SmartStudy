import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from models import ChatSession


class SessionManager:
    """Thread-safe store for active chat sessions with TTL-based expiry."""

    def __init__(self, ttl_hours: Optional[float] = None):
        self._sessions: Dict[str, ChatSession] = {}
        self._lock = threading.Lock()
        self.ttl_hours = ttl_hours if ttl_hours is not None else float(
            os.getenv("CHAT_SESSION_TTL_HOURS", "24")
        )

    def create(self, subject: str, title: str = "New Chat",
               grade: Optional[int] = None) -> str:
        """Create a new session and return its ID."""
        self._cleanup_expired()
        session = ChatSession(subject=subject, title=title, grade=grade)
        with self._lock:
            self._sessions[session.id] = session
        return session.id

    def get(self, session_id: str) -> Optional[ChatSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def update_title(self, session_id: str, new_title: str) -> bool:
        with self._lock:
            if session := self._sessions.get(session_id):
                session.title = new_title
                return True
        return False

    def _cleanup_expired(self) -> None:
        if self.ttl_hours <= 0:
            return
        cutoff = datetime.now() - timedelta(hours=self.ttl_hours)
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if s.created_at < cutoff]
            for sid in expired:
                del self._sessions[sid]
