"""Study-notes generation: core + applied sections run in parallel; DeepSeek-cached
prompts; validation is fire-and-forget."""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from models import TokenCount
from prompts import (_NOTES_APPLIED_HUMAN, _NOTES_APPLIED_SYSTEM, _NOTES_CORE_HUMAN,
                     _NOTES_CORE_SYSTEM, _NOTES_EXTRA_HUMAN, _NOTES_EXTRA_SYSTEM)
from subject_rules import (STEM_SUBJECTS, get_grounding_rule, get_subject_focus,
                           get_subject_rules, presentation_rules)
from utils import format_docs, gen_semaphore, parse_llm_response


class NotesMixin:
    async def generate_notes(self, subject: str, topic: str, grade: Optional[int] = None,
                             unit: Optional[str] = None, version: str = "1.0",
                             chat_context: str | None = None) -> Dict[str, Any]:
        """Generate comprehensive study notes with examples and explanations."""
        from types import SimpleNamespace
        token_usage = TokenCount(0, 0, 0.0)
        try:
            _t_total = time.perf_counter()
            coverage_task = None
            if chat_context:
                context_response = SimpleNamespace(
                    error=None,
                    context=[chat_context],
                    parsed_answer={"key_concepts": [], "areas": [], "keypoints": []},
                )
            else:
                # Milvus-only retrieval, then the topic-coverage check runs CONCURRENTLY
                # with generation below rather than gating it. On the common covered case
                # its round-trip folds under the generation tail (saves ~5-10s); on the rare
                # not-covered case the generation output is discarded. Coverage judging only
                # needs a sample of the context, so cap it to keep that call's prefill small.
                _t0 = time.perf_counter()
                context_response = await self.context_agent.query_documents_only(
                    subject=subject,
                    question=f"Generate detailed comprehensive notes about {topic}",
                    grade=grade, unit=unit, type_req="notes"
                )
                self.logger.info("[notes] retrieval: %.2fs", time.perf_counter() - _t0)
                if context_response.error:
                    return {"error": context_response.error}
                coverage_task = asyncio.create_task(
                    self.validation_agent.validate_coverage_from_context(
                        topic=topic,
                        context=context_response.context[:15],
                        subject=subject,
                        grade=grade,
                        unit=unit,
                    )
                )

            subject_rules = get_subject_rules(subject)
            subject_focus = get_subject_focus(subject) or "- No additional subject focus."
            grounding_rule = get_grounding_rule(subject)
            pres_rules = presentation_rules()

            prompt_core = ChatPromptTemplate.from_messages([
                ("system", _NOTES_CORE_SYSTEM),
                ("human", _NOTES_CORE_HUMAN),
            ])

            # Applied (formulas/worked-examples/real-world) and extra (practice-problems/
            # review-questions) run in parallel with the core call — disjoint output keys.
            prompt_applied = ChatPromptTemplate.from_messages([
                ("system", _NOTES_APPLIED_SYSTEM),
                ("human", _NOTES_APPLIED_HUMAN),
            ])
            prompt_extra = ChatPromptTemplate.from_messages([
                ("system", _NOTES_EXTRA_SYSTEM),
                ("human", _NOTES_EXTRA_HUMAN),
            ])

            _invoke_args = {
                "context": format_docs(context_response.context),
                "topic": topic,
                "subject": subject,
                "rules": subject_rules,
                "subject_focus": subject_focus,
                "grounding_rule": grounding_rule,
                "presentation_rules": pres_rules,
            }

            async def _invoke(prompt):
                # Bound under the shared generation semaphore (same as mcq/flashcards).
                async with gen_semaphore():
                    return await (prompt | self._json_llm | StrOutputParser()).ainvoke(_invoke_args)

            # Core (conceptual), applied (practical) and extra (practice+review) run in
            # parallel — three ~1/3-size decodes instead of two halves, shrinking the tail
            # (biggest win for STEM, where applied+extra sections are large). Kicked off
            # before we resolve coverage so they overlap the coverage check.
            _t0 = time.perf_counter()
            gen_task = asyncio.gather(
                _invoke(prompt_core),
                _invoke(prompt_applied),
                _invoke(prompt_extra),
            )

            if coverage_task is not None:
                coverage = await coverage_task
                if not coverage.get("is_covered", True):
                    gen_task.cancel()
                    try:
                        await gen_task  # retrieve the cancellation so it isn't logged as unhandled
                    except (asyncio.CancelledError, Exception):
                        pass
                    available = coverage.get("available_topics", [])
                    suffix = (
                        f" Topics available in this unit: {', '.join(available)}."
                        if available else ""
                    )
                    scope = f"{subject.title()}"
                    if grade:
                        scope += f" Grade {grade}"
                    if unit:
                        scope += f" Unit {unit}"
                    return {
                        "error": "topic_not_in_unit",
                        "message": (
                            f"'{topic}' is not covered in the {scope} curriculum.{suffix}"
                        ),
                        "available_topics": available,
                    }

            response_core, response_applied, response_extra = await gen_task
            self.logger.info("[notes] generation (core+applied+extra parallel): %.2fs", time.perf_counter() - _t0)
            parsed_core = parse_llm_response(str(response_core), self.logger)
            parsed_applied = parse_llm_response(str(response_applied), self.logger)
            parsed_extra = parse_llm_response(str(response_extra), self.logger)
            parsed_response = {**parsed_core, **parsed_applied, **parsed_extra}

            required_sections = ["title", "overview", "learning_objectives", "key_concepts", "real_world_applications"]
            if subject.lower() in STEM_SUBJECTS:
                required_sections += ["worked_examples", "practice_problems"]

            missing = [k for k in required_sections if k not in parsed_response]
            if missing:
                self.logger.error(
                    "[notes] missing required sections: %s | core keys: %s | applied keys: %s | extra keys: %s",
                    missing, list(parsed_core.keys()), list(parsed_applied.keys()), list(parsed_extra.keys()),
                )
                raise ValueError(f"Generated notes missing required sections: {missing}")

            # validate_notes is fail-open (only logs) — run it as a background task so it
            # doesn't block the response.
            async def _bg_validate_notes():
                r = await self.validation_agent.validate_notes(parsed_response, context_response.context)
                if not r.get("is_valid", True):
                    self.logger.warning("Notes validation flagged: %s", r.get("reason", ""))

            asyncio.create_task(_bg_validate_notes())

            parsed_response["metadata"] = {
                "subject": subject,
                "topic": topic,
                "grade": grade,
                "unit": unit,
                "generated_at": datetime.now().isoformat(),
                "complexity_level": "comprehensive",
                "estimated_study_time": "45-60 minutes",
                "version": version,
                "is_valid": True,
                "validation_note": "",
            }

            token_usage = self._record_token_usage(
                f"{format_docs(context_response.context)}\n{subject_rules}",
                str(parsed_response)
            )

            self.logger.info("[notes] total: %.2fs", time.perf_counter() - _t_total)
            return {"notes": parsed_response, "error": None, "token_usage": str(token_usage)}

        except Exception as e:
            self.logger.error(f"Error generating notes: {e}")
            return {"error": f"Notes generation failed: {e}", "token_usage": str(token_usage)}

