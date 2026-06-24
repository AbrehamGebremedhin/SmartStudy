"""Shared base for the generation mixins: LLM/agent wiring, token accounting,
context helpers, and chat-session delegation. The public class is GenerationAgent,
which combines the per-type mixins (mcq, flashcards, notes, chat, evaluation)."""

import logging
import os
from typing import Optional

import tiktoken
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from ContextRefinementAgent import ContextRefinementAgent
from ValidationAgent import ValidationAgent
from models import ChatSession, TokenCount
from session_manager import SessionManager

load_dotenv("./.env")


class GenerationBase:
    """LLM wiring, token accounting, context helpers, and session delegation."""

    def __init__(self):
        load_dotenv("./.env")
        self.logger = logging.getLogger(__name__)

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment")

        self.llm = ChatDeepSeek(model="deepseek-v4-flash", api_key=api_key)
        self._json_llm = self.llm.bind(response_format={"type": "json_object"})
        self.context_agent = ContextRefinementAgent()
        self.validation_agent = ValidationAgent()
        self.sessions = SessionManager()
        # NOTE: tiktoken's gpt-3.5-turbo encoding is an approximation for DeepSeek.
        # Token counts and cost estimates are indicative only.
        self._token_encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.COST_PER_1M_INPUT = 0.14   # DeepSeek-V4-Flash
        self.COST_PER_1M_OUTPUT = 0.28  # DeepSeek-V4-Flash

    def _count_tokens(self, text: str) -> int:
        return len(self._token_encoder.encode(str(text)))

    def _record_token_usage(self, input_text: str, output_text: str) -> TokenCount:
        inp = self._count_tokens(input_text)
        out = self._count_tokens(output_text)
        cost = (inp * self.COST_PER_1M_INPUT + out * self.COST_PER_1M_OUTPUT) / 1_000_000
        return TokenCount(inp, out, cost)

    def create_chat_session(self, subject: str, initial_title: str = "New Chat",
                            grade: Optional[int] = None) -> str:
        return self.sessions.create(subject, title=initial_title, grade=grade)

    def get_chat_session(self, session_id: str) -> Optional[ChatSession]:
        return self.sessions.get(session_id)

    def update_session_title(self, session_id: str, new_title: str) -> bool:
        return self.sessions.update_title(session_id, new_title)

    def _extract_note_context(self, note_content: dict) -> str:
        """Format the MCQ/flashcard-relevant sections of a note as a plain-text context string."""
        parts = []
        title = note_content.get("title", "")
        if title:
            parts.append(f"Topic: {title}")

        for concept in note_content.get("key_concepts", []):
            name = concept.get("concept", "")
            explanation = concept.get("detailed_explanation", "")
            sub = concept.get("sub_concepts", [])
            misconceptions = concept.get("common_misconceptions", [])
            block = f"Concept: {name}\n{explanation}"
            if sub:
                sub_strs = [
                    s.get("name", str(s)) if isinstance(s, dict) else str(s)
                    for s in sub
                ]
                block += "\n  Sub-concepts: " + "; ".join(sub_strs)
            if misconceptions:
                misc_strs = [
                    m.get("misconception", str(m)) if isinstance(m, dict) else str(m)
                    for m in misconceptions
                ]
                block += "\n  Common misconceptions: " + "; ".join(misc_strs)
            parts.append(block)

        framework = note_content.get("theoretical_framework", {})
        for principle in framework.get("principles", []):
            parts.append(f"Principle: {principle}")
        for theory in framework.get("theories", []):
            parts.append(f"Theory — {theory.get('name', '')}: {theory.get('explanation', '')}")

        for formula in note_content.get("formulas_and_equations", []):
            parts.append(f"Formula: {formula.get('formula', '')}")

        return "\n\n".join(p for p in parts if p.strip())

    def _format_chat_as_context(self, messages: list) -> str:
        """Format chat messages as a readable context string, including key concepts."""
        lines = []
        all_concepts: list = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"Student: {content}")
            elif role == "assistant":
                lines.append(f"Teacher: {content}")
                for concept in msg.get("key_concepts", []):
                    if concept not in all_concepts:
                        all_concepts.append(concept)

        result = "\n".join(lines)
        if all_concepts:
            result += f"\n\nKey concepts covered: {', '.join(all_concepts)}"
        return result

