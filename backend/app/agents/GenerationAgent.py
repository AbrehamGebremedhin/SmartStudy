"""Public generation agent.

Combines the per-type mixins into one interface so call sites use GenerationAgent
unchanged. Shared wiring lives in base; each generation type has its own module."""

from base import GenerationBase
from chat import ChatMixin
from evaluation import EvalMixin
from flashcards import FlashcardMixin
from mcq import MCQMixin
from notes import NotesMixin


class GenerationAgent(MCQMixin, FlashcardMixin, NotesMixin, ChatMixin, EvalMixin, GenerationBase):
    """Generates MCQs, flashcards, study notes, tutor chat, and answer evaluations."""
