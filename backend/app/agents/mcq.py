"""MCQ generation: parallel across context slices + overlapped validation,
DeepSeek-cached prompt."""

import asyncio
import time
from typing import Any, Dict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from mcq_utils import is_test_prep_artifact, redistribute_answer_positions
from models import TokenCount
from prompts import _MCQ_HUMAN, _MCQ_SYSTEM
from subject_rules import get_grounding_rule, get_mcq_subject_guidance, get_subject_rules
from utils import format_docs, parse_llm_response, retry_on_none


class MCQMixin:
    async def _retrieve_mcq_context(self, subject: str, grade: int, unit: str, difficulty: str):
        if subject.lower() == "sat":
            question = (
                f"{difficulty} aptitude material: vocabulary and word meanings, synonyms and "
                f"antonyms, analogies and word relationships, reading comprehension passages, "
                f"sentence correction and grammar, logical reasoning, and quantitative problem "
                f"solving (arithmetic, percentages, ratios, algebra, data interpretation)"
            )
        else:
            question = f"Generate {difficulty} MCQs for this content"

        return await self.context_agent.query_documents_only(
            subject=subject, question=question,
            grade=grade, unit=unit, type_req="quiz",
        )

    @retry_on_none(max_retries=3)
    async def generate_mcqs(self, subject: str, grade: int, unit: str,
                            topic: str | None = None,
                            note_content: dict | None = None,
                            chat_context: str | None = None,
                            num_questions: int = 5, difficulty: str = "hard") -> Dict[str, Any]:
        """Generate multiple choice questions with comprehensive validation."""
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
                question = f"Generate {difficulty} MCQs for this content on the topic of {topic}"
                context_response = await self.context_agent.query_documents_only(
                    subject=subject, question=question,
                    grade=None, unit=None, type_req="quiz",
                )
            else:
                context_response = await self._retrieve_mcq_context(subject, grade, unit, difficulty)
            self.logger.info("[mcq] retrieval: %.2fs", time.perf_counter() - _t0)
            if context_response.error:
                return {"error": context_response.error}

            subject_rules = get_subject_rules(subject)
            subject_guidance = get_mcq_subject_guidance(subject) or "- No additional subject-specific rules."
            grounding_rule = get_grounding_rule(subject)

            prompt = ChatPromptTemplate.from_messages([
                ("system", _MCQ_SYSTEM),
                ("human", _MCQ_HUMAN),
            ])

            chain = prompt | self._json_llm | StrOutputParser()
            # Over-generate by a small buffer so the sequential top-up call is rarely needed.
            # The floor (min buffer) matters most at the common small counts; the extra item is
            # split across K parallel calls, so it barely adds to per-call decode.
            # ponytail: floor=3 is a conservative default — tune the buffer from the Phase-0
            # top-up/shortfall logs ([mcq] top-up ...) once real-traffic data exists.
            generate_count = num_questions + max(3, num_questions // 4)
            base_args = {
                "num_questions": generate_count,
                "subject_rules": subject_rules,
                "subject_guidance": subject_guidance,
                "grounding_rule": grounding_rule,
                "difficulty": difficulty,
            }

            # Parallel generation + overlapped validation. LLM decode is sequential, so
            # one call producing N questions costs ~N x a single question's decode. Split
            # the work across K calls on DISJOINT slices of the retrieved context (natural
            # topic diversity, no cross-call coordination needed) and validate each chunk
            # as it returns, so the validation round-trip folds under the generation tail
            # instead of adding to it. Same model, same prompt, same per-question quality.
            # ponytail: K capped at 3 to bound DeepSeek concurrency (each request fans out
            # to <=2K+1 calls). Add a global semaphore if DeepSeek starts throttling.
            docs = context_response.context if isinstance(context_response.context, list) \
                else [context_response.context]
            K = max(1, min(num_questions, 3, len(docs)))
            per_call = (generate_count + K - 1) // K
            slices = [docs[i::K] for i in range(K)] if K > 1 else [docs]

            async def _gen_and_validate(doc_slice):
                if not doc_slice:
                    return []
                resp = await chain.ainvoke({**base_args, "num_questions": per_call,
                                            "context": format_docs(doc_slice)})
                parsed = parse_llm_response(str(resp), self.logger)
                qs = parsed.get("questions", [])
                if not qs:
                    return []
                vr = await self.validation_agent.validate_mcqs(qs, doc_slice[:12])
                return vr["valid_mcqs"]

            _t0 = time.perf_counter()
            chunk_results = await asyncio.gather(
                *[_gen_and_validate(s) for s in slices], return_exceptions=True)
            self.logger.info("[mcq] gen+validate (K=%d parallel): %.2fs", K, time.perf_counter() - _t0)

            valid_questions: list = []
            for r in chunk_results:
                if isinstance(r, list):
                    valid_questions.extend(r)
                else:
                    self.logger.error("[mcq] chunk failed: %s", r)
            if not valid_questions:
                return None  # triggers @retry_on_none

            # Parallel chunks can't see each other's topics, so dedup across them by exact
            # question text and topic label — backstops the per-call UNIQUE TOPICS rule.
            seen_q: set = set()
            seen_topic: set = set()
            deduped: list = []
            for q in valid_questions:
                qt = str(q.get("question", "")).strip().lower()
                tp = str(q.get("topic", "")).strip().lower()
                if (qt and qt in seen_q) or (tp and tp in seen_topic):
                    continue
                if qt:
                    seen_q.add(qt)
                if tp:
                    seen_topic.add(tp)
                deduped.append(q)
            valid_questions = deduped

            valid_questions = [
                q for q in valid_questions
                if not is_test_prep_artifact(subject, q.get("topic"), q.get("question"), q.get("passage"))
            ]

            # Top-up: filters may have dropped questions below the requested count.
            # One sequential call on the full context, with the same filters.
            shortfall = num_questions - len(valid_questions)
            if shortfall > 0:
                _t0 = time.perf_counter()
                topup_response = await chain.ainvoke({**base_args, "num_questions": shortfall + 2,
                                                      "context": format_docs(docs[:12])})
                topup_parsed = parse_llm_response(str(topup_response), self.logger)
                topup_questions = [
                    q for q in topup_parsed.get("questions", [])
                    if not is_test_prep_artifact(subject, q.get("topic"), q.get("question"), q.get("passage"))
                ]
                valid_questions = valid_questions + topup_questions
                self.logger.info("[mcq] top-up (shortfall=%d): %.2fs", shortfall, time.perf_counter() - _t0)

            valid_questions = redistribute_answer_positions(valid_questions)

            _none_like = ("N/A", "NA", "NONE", "-", "NOT APPLICABLE", "NULL")
            for q in valid_questions:
                q["difficulty"] = difficulty
                ws = q.get("workout_steps")
                if not ws or str(ws).strip().upper() in _none_like:
                    q["workout_steps"] = None
                passage = q.get("passage")
                if not passage or str(passage).strip().upper() in _none_like:
                    q["passage"] = None

            token_usage = self._record_token_usage(
                f"{format_docs(context_response.context)}\n{subject_rules}\n{difficulty}",
                str(valid_questions)
            )

            self.logger.info("[mcq] total: %.2fs", time.perf_counter() - _t_total)
            return {
                "questions": valid_questions[:num_questions],
                "error": None,
                "difficulty": difficulty,
                "token_usage": str(token_usage)
            }

        except Exception as e:
            self.logger.error(f"Error generating MCQs: {e}")
            return {"error": f"MCQ generation failed: {e}", "difficulty": difficulty, "token_usage": str(token_usage)}

