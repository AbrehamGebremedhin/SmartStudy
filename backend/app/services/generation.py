"""
Wraps the GenerationAgent for use from the FastAPI service layer.

The agents were written with bare module imports (no package prefix) and must
run with app/agents on sys.path. We add it here once so all agent imports
resolve without touching the agent files.
"""

import logging
import sys
from pathlib import Path

from langchain_core.callbacks import get_usage_metadata_callback

_agents_dir = str(Path(__file__).resolve().parents[1] / "agents")
if _agents_dir not in sys.path:
    sys.path.insert(0, _agents_dir)

from GenerationAgent import GenerationAgent  # noqa: E402  (after sys.path patch)
from utils import TokenAccountant  # noqa: E402  (after sys.path patch)

from app.security.output_sanitizer import sanitize_output

logger = logging.getLogger(__name__)

_agent: GenerationAgent | None = None


def get_agent() -> GenerationAgent:
    global _agent
    if _agent is None:
        _agent = GenerationAgent()
    return _agent


def _apply_real_usage(result: dict, cb) -> None:
    """Overwrite result['token_usage'] with the request's REAL aggregated usage.

    The agent's own token_usage is a tiktoken approximation of a single string; the
    usage-metadata callback captures actual provider-reported tokens across every LLM
    call the request made (generation + inline validation + top-up), including the
    prompt-cache read count — so we also learn whether the DeepSeek prefix cache is
    hitting. Kept in TokenCount's exact string format so cache._parse_token_usage and
    the stored DB columns keep working unchanged.
    """
    inp = out = cache_read = 0
    for md in cb.usage_metadata.values():
        inp += md.get("input_tokens", 0)
        out += md.get("output_tokens", 0)
        cache_read += (md.get("input_token_details") or {}).get("cache_read", 0) or 0
    if not (inp or out):
        return  # no LLM calls captured (e.g. pure cache hit) — leave agent's value
    cost = (inp * TokenAccountant.COST_PER_1M_INPUT
            + out * TokenAccountant.COST_PER_1M_OUTPUT) / 1_000_000
    logger.info("[usage] in=%d out=%d cache_read=%d (%.0f%% of input cached)",
                inp, out, cache_read, (100.0 * cache_read / inp) if inp else 0.0)
    if isinstance(result, dict):
        result["token_usage"] = (
            f"Input tokens: {inp}\n"
            f"Output tokens: {out}\n"
            f"Total tokens: {inp + out}\n"
            f"Estimated cost: ${cost:.4f}"
        )


async def run_generate_mcqs(
    subject: str,
    grade: int | None,
    unit: str | None,
    topic: str | None,
    num_questions: int,
    difficulty: str,
    note_content: dict | None = None,
    chat_context: str | None = None,
) -> dict:
    agent = get_agent()
    with get_usage_metadata_callback() as cb:
        result = await agent.generate_mcqs(
            subject=subject,
            grade=grade,
            unit=unit,
            topic=topic,
            note_content=note_content,
            chat_context=chat_context,
            num_questions=num_questions,
            difficulty=difficulty,
        )
    _apply_real_usage(result, cb)
    return sanitize_output(result)


async def run_generate_flashcards(
    subject: str,
    grade: int | None,
    unit: str | None,
    topic: str | None,
    num_cards: int,
    difficulty: str,
    note_content: dict | None = None,
    chat_context: str | None = None,
) -> dict:
    agent = get_agent()
    with get_usage_metadata_callback() as cb:
        result = await agent.generate_flashcards(
            subject=subject,
            grade=grade,
            unit=unit,
            topic=topic,
            num_cards=num_cards,
            difficulty=difficulty,
            note_content=note_content,
            chat_context=chat_context,
        )
    _apply_real_usage(result, cb)
    return sanitize_output(result)


async def run_generate_notes(
    subject: str,
    topic: str,
    grade: int | None,
    unit: str | None,
    version: str,
    chat_context: str | None = None,
) -> dict:
    agent = get_agent()
    with get_usage_metadata_callback() as cb:
        result = await agent.generate_notes(
            subject=subject,
            topic=topic,
            grade=grade,
            unit=unit,
            version=version,
            chat_context=chat_context,
        )
    _apply_real_usage(result, cb)
    return sanitize_output(result)


async def run_note_chat(
    note_content: dict,
    subject: str,
    question: str,
    chat_history_str: str = "",
) -> dict:
    agent = get_agent()
    with get_usage_metadata_callback() as cb:
        result = await agent.note_chat_response(
            note_content=note_content,
            subject=subject,
            question=question,
            chat_history_str=chat_history_str,
        )
    _apply_real_usage(result, cb)
    return sanitize_output(result)


async def run_chat_response(
    subject: str,
    question: str,
    session_id: str | None,
    grade: int | None,
    chat_history_str: str = "",
) -> dict:
    agent = get_agent()
    with get_usage_metadata_callback() as cb:
        result = await agent.chat_response(
            subject=subject,
            question=question,
            session_id=session_id,
            grade=grade,
            chat_history_str=chat_history_str,
        )
    _apply_real_usage(result, cb)
    return sanitize_output(result)


async def run_chat_context(subject: str, grade: int | None, title: str) -> dict:
    """Query the vector DB using the session title to extract the most likely grade and unit."""
    from collections import Counter
    gen_agent = get_agent()
    question = title if title and title != "New Chat" else f"context for {subject}"
    ctx = await gen_agent.context_agent.query_documents_only(
        subject=subject, question=question, grade=grade, unit=None, type_req="chat"
    )
    if ctx.error or not isinstance(ctx.context, list) or not ctx.context:
        return {"grade": grade, "unit": None}

    units, grades = [], []
    for doc in ctx.context:
        if not hasattr(doc, "metadata"):
            continue
        u = doc.metadata.get("unit")
        g = doc.metadata.get("grade")
        if u is not None and str(u).strip():
            units.append(str(u).strip())
        if g is not None and str(g).strip():
            grades.append(str(g).strip())

    result_grade = grade
    result_unit = None
    if grades:
        try:
            result_grade = int(Counter(grades).most_common(1)[0][0])
        except (ValueError, TypeError):
            pass
    if units:
        result_unit = Counter(units).most_common(1)[0][0]
    return {"grade": result_grade, "unit": result_unit}


async def run_evaluate_answer(
    subject: str,
    question: dict,
    student_answer: str,
    note: dict | None,
) -> dict:
    agent = get_agent()
    with get_usage_metadata_callback() as cb:
        result = await agent.evaluate_practice_answer(
            subject=subject,
            question=question,
            student_answer=student_answer,
            note=note,
        )
    _apply_real_usage(result, cb)
    return sanitize_output(result)
