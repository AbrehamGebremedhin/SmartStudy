"""
Wraps the GenerationAgent for use from the FastAPI service layer.

The agents were written with bare module imports (no package prefix) and must
run with app/agents on sys.path. We add it here once so all agent imports
resolve without touching the agent files.
"""

import sys
from pathlib import Path

_agents_dir = str(Path(__file__).resolve().parents[1] / "agents")
if _agents_dir not in sys.path:
    sys.path.insert(0, _agents_dir)

from GenerationAgent import GenerationAgent  # noqa: E402  (after sys.path patch)

_agent: GenerationAgent | None = None


def get_agent() -> GenerationAgent:
    global _agent
    if _agent is None:
        _agent = GenerationAgent()
    return _agent


async def run_generate_mcqs(
    subject: str,
    grade: int | None,
    unit: str | None,
    num_questions: int,
    difficulty: str,
) -> dict:
    agent = get_agent()
    return await agent.generate_mcqs(
        subject=subject,
        grade=grade,
        unit=unit,
        num_questions=num_questions,
        difficulty=difficulty,
    )


async def run_generate_flashcards(
    subject: str,
    grade: int | None,
    unit: str | None,
    topic: str | None,
    num_cards: int,
    difficulty: str,
) -> dict:
    agent = get_agent()
    return await agent.generate_flashcards(
        subject=subject,
        grade=grade,
        unit=unit,
        topic=topic,
        num_cards=num_cards,
        difficulty=difficulty,
    )


async def run_generate_notes(
    subject: str,
    topic: str,
    grade: int | None,
    unit: str | None,
    version: str,
) -> dict:
    agent = get_agent()
    return await agent.generate_notes(
        subject=subject,
        topic=topic,
        grade=grade,
        unit=unit,
        version=version,
    )


async def run_chat_response(
    subject: str,
    question: str,
    session_id: str | None,
    grade: int | None,
    chat_history_str: str = "",
) -> dict:
    agent = get_agent()
    return await agent.chat_response(
        subject=subject,
        question=question,
        session_id=session_id,
        grade=grade,
        chat_history_str=chat_history_str,
    )


async def run_evaluate_answer(
    subject: str,
    question: dict,
    student_answer: str,
    note: dict | None,
) -> dict:
    agent = get_agent()
    return await agent.evaluate_practice_answer(
        subject=subject,
        question=question,
        student_answer=student_answer,
        note=note,
    )
