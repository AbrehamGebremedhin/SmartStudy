from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import uuid


@dataclass
class ChatMessage:
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    key_concepts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "message": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.role == "assistant" and self.key_concepts:
            d["key_concepts"] = self.key_concepts
        return d


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    messages: List[ChatMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    subject: str = ""
    grade: Optional[int] = None

    def add_message(self, role: str, content: str, key_concepts: Optional[List[str]] = None):
        self.messages.append(ChatMessage(
            role=role,
            content=content,
            key_concepts=key_concepts or [],
        ))

    def get_recent_context(self, max_messages: int = 10) -> str:
        """Return the last N messages formatted for the LLM.

        Call this BEFORE appending the current user question so the result
        contains only prior context, with no duplication.
        """
        recent = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        return "\n".join(f"{m.role}: {m.content}" for m in recent)

    def get_history_as_list(self) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self.messages]


@dataclass
class TokenCount:
    input_tokens: int
    output_tokens: int
    total_cost: float

    def __str__(self):
        return (
            f"Input tokens: {self.input_tokens}\n"
            f"Output tokens: {self.output_tokens}\n"
            f"Total tokens: {self.input_tokens + self.output_tokens}\n"
            f"Estimated cost: ${self.total_cost:.4f}"
        )
