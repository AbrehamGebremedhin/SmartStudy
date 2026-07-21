"""Flashcard generation: parallel across context slices; validation runs in the
background; DeepSeek-cached prompt."""

import asyncio
import re
import time
from typing import Any, Dict, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from mcq_utils import is_test_prep_artifact
from models import TokenCount
from prompts import _FLASHCARD_HUMAN, _FLASHCARD_SYSTEM
from subject_rules import (get_grounding_rule, get_subject_focus, get_subject_rules,
                           presentation_rules)
from utils import format_docs, gen_semaphore, parse_llm_response, retry_on_none


class FlashcardMixin:
    @retry_on_none(max_retries=3)
    async def generate_flashcards(self, subject: str, num_cards: int = 5,
                                  topic: Optional[str] = None, grade: Optional[int] = None,
                                  unit: Optional[str] = None, difficulty: str = "medium",
                                  note_content: dict | None = None,
                                  chat_context: str | None = None) -> Dict[str, Any]:
        """Generate educational flashcards with validation."""
        from types import SimpleNamespace
        token_usage = TokenCount(0, 0, 0.0)
        try:
            _t_total = time.perf_counter()
            if difficulty not in ["easy", "medium", "hard", "challenging"]:
                difficulty = "medium"

            _t0 = time.perf_counter()
            if note_content:
                context_str = self._extract_note_context(note_content)
                context_response = SimpleNamespace(
                    error=None,
                    context=[context_str],
                    parsed_answer={"areas": [], "key_concepts": []},
                )
            elif chat_context:
                context_response = SimpleNamespace(
                    error=None,
                    context=[chat_context],
                    parsed_answer={"areas": [], "key_concepts": []},
                )
            elif topic:
                question = f"Generate {difficulty} flashcards for this content on the topic of {topic}"
                context_response = await self.context_agent.query_documents_only(
                    subject=subject, question=question,
                    grade=None, unit=None, type_req="quiz",
                )
            elif subject.lower() == "sat":
                question = (
                    f"{difficulty} aptitude material: vocabulary, synonyms and antonyms, "
                    f"analogies, classification, sentence correction, reading and verbal "
                    f"reasoning, and quantitative problem solving"
                )
                context_response = await self.context_agent.query_documents_only(
                    subject=subject, question=question, grade=grade, unit=unit, type_req="quiz"
                )
            else:
                question = f"Generate {difficulty} flashcards for this content"
                context_response = await self.context_agent.query_documents_only(
                    subject=subject, question=question, grade=grade, unit=unit, type_req="quiz"
                )

            self.logger.info("[flashcard] retrieval: %.2fs", time.perf_counter() - _t0)
            if context_response.error:
                return {"error": context_response.error}
            if not context_response.context:
                return {"error": "No relevant documents found"}

            subject_rules = get_subject_rules(subject)
            subject_focus = get_subject_focus(subject) or "- No additional subject focus."
            grounding_rule = get_grounding_rule(subject)
            pres_rules = presentation_rules()

            prompt = ChatPromptTemplate.from_messages([
                ("system", _FLASHCARD_SYSTEM),
                ("human", _FLASHCARD_HUMAN),
            ])

            chain = prompt | self._json_llm | StrOutputParser()
            # Over-generate by a small buffer so the sequential top-up call is rarely needed.
            # ponytail: floor=3 is a conservative default — tune from the Phase-0 top-up logs
            # ([flashcard] top-up ...) once real-traffic data exists.
            generate_count = num_cards + max(3, num_cards // 4)
            base_args = {
                "num_cards": generate_count,
                "difficulty": difficulty,
                "subject_rules": subject_rules,
                "subject_focus": subject_focus,
                "grounding_rule": grounding_rule,
                "presentation_rules": pres_rules,
            }

            # Parallel generation across disjoint context slices (see generate_mcqs) — decode
            # is sequential, so K smaller calls finish in ~1/K the wall time at the same
            # per-card quality. K up to 6; the global gen_semaphore bounds cross-request
            # DeepSeek concurrency. Validation stays fire-and-forget below.
            docs = context_response.context if isinstance(context_response.context, list) \
                else [context_response.context]
            K = max(1, min(num_cards, 6, len(docs)))
            per_call = (generate_count + K - 1) // K
            slices = [docs[i::K] for i in range(K)] if K > 1 else [docs]

            async def _gen_cards(doc_slice):
                if not doc_slice:
                    return []
                async with gen_semaphore():
                    resp = await chain.ainvoke({**base_args, "num_cards": per_call,
                                                "context": format_docs(doc_slice)})
                parsed = parse_llm_response(str(resp), self.logger)
                return parsed.get("flashcards", [])

            _t0 = time.perf_counter()
            chunk_results = await asyncio.gather(*[_gen_cards(s) for s in slices], return_exceptions=True)
            self.logger.info("[flashcard] generation (K=%d parallel): %.2fs", K, time.perf_counter() - _t0)
            valid_cards: list = []
            for r in chunk_results:
                if isinstance(r, list):
                    valid_cards.extend(r)
                else:
                    self.logger.error("[flashcard] chunk failed: %s", r)
            if not valid_cards:
                return None  # triggers retry in caller

            # Validation is fire-and-forget — quality is already controlled by over-generation
            # and the dedup/filter pass below, so we don't block the response on it.
            _validation_cards = list(valid_cards)
            _validation_ctx = docs[:12]

            async def _bg_validate_flashcards():
                _t = time.perf_counter()
                r = await self.validation_agent.validate_flashcards(
                    _validation_cards, _validation_ctx
                )
                self.logger.info("[flashcard] bg-validation: %.2fs | valid=%d/%d",
                                 time.perf_counter() - _t,
                                 len(r.get("valid_flashcards", [])), len(_validation_cards))

            asyncio.create_task(_bg_validate_flashcards())

            valid_cards = [
                c for c in valid_cards
                if not is_test_prep_artifact(subject, c.get("front"), c.get("back"), c.get("topic"))
            ]

            # Top-up: filters may have dropped cards below the requested count.
            shortfall = num_cards - len(valid_cards)
            if shortfall > 0:
                _t0 = time.perf_counter()
                async with gen_semaphore():
                    topup_response = await chain.ainvoke({**base_args, "num_cards": shortfall + 2,
                                                          "context": format_docs(docs[:12])})
                topup_parsed = parse_llm_response(str(topup_response), self.logger)
                topup_cards = [
                    c for c in topup_parsed.get("flashcards", [])
                    if not is_test_prep_artifact(subject, c.get("front"), c.get("back"), c.get("topic"))
                ]
                valid_cards = valid_cards + topup_cards
                self.logger.info("[flashcard] top-up (shortfall=%d): %.2fs", shortfall, time.perf_counter() - _t0)

            def _normalise(text: str) -> frozenset:
                return frozenset(re.sub(r"[^\w]", " ", text.lower()).split())

            def _focus_word(front: str) -> Optional[str]:
                m = re.search(r"['\"]([A-Za-z]{4,})['\"]", front)
                if m:
                    return m.group(1).lower()
                m = re.search(r"\b([A-Z]{4,})\b", front)
                if m:
                    return m.group(1).lower()
                return None

            seen_fronts: set = set()
            seen_focus: set = set()
            deduped: list = []
            for c in valid_cards:
                front_text = str(c.get("front", ""))
                key = _normalise(front_text)
                focus = _focus_word(front_text)
                if key in seen_fronts or (focus and focus in seen_focus):
                    continue
                seen_fronts.add(key)
                if focus:
                    seen_focus.add(focus)
                deduped.append(c)
            valid_cards = deduped

            for card in valid_cards:
                card["difficulty"] = difficulty

            token_usage = self._record_token_usage(
                f"{format_docs(context_response.context)}\n{subject_rules}\n{difficulty}",
                str(valid_cards)
            )

            self.logger.info("[flashcard] total: %.2fs", time.perf_counter() - _t_total)
            return {
                "flashcards": valid_cards[:num_cards],
                "error": None,
                "difficulty": difficulty,
                "token_usage": str(token_usage)
            }

        except Exception as e:
            self.logger.error(f"Error generating flashcards: {e}")
            return {"error": f"Flashcard generation failed: {e}", "difficulty": difficulty, "token_usage": str(token_usage)}

