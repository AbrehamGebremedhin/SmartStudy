"""Practice-answer evaluation; DeepSeek-cached prompt."""

import json
from typing import Any, Dict, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from models import TokenCount
from prompts import _EVAL_HUMAN, _EVAL_SYSTEM
from subject_rules import get_grounding_rule, get_subject_rules
from utils import clean_unicode, format_docs


class EvalMixin:
    def _extract_note_eval_context(self, note: Dict[str, Any], question_text: str) -> str:
        """Extract relevant context from a generated note for answer evaluation."""
        parts = []

        title = note.get("title", "")
        if title:
            parts.append(f"Topic: {title}")

        overview = note.get("overview", {})
        if isinstance(overview, dict) and overview.get("brief_summary"):
            parts.append(f"Overview: {overview['brief_summary']}")

        key_concepts = note.get("key_concepts", [])
        if key_concepts:
            parts.append("Key Concepts:")
            for kc in key_concepts:
                if isinstance(kc, dict):
                    parts.append(f"- {kc.get('concept', '')}: {kc.get('detailed_explanation', '')}")

        review_questions = note.get("review_questions", [])
        matched_q = next(
            (rq for rq in review_questions if isinstance(rq, dict) and rq.get("question", "").strip() == question_text.strip()),
            None
        )
        if matched_q:
            parts.append(f"\nExpected key points for this question: {', '.join(matched_q.get('key_points', []))}")
            parts.append(f"Suggested answer: {matched_q.get('suggested_answer', '')}")

        return "\n".join(parts)

    async def evaluate_practice_answer(self, subject: str, question: Dict[str, Any],
                                       student_answer: str,
                                       note: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token_usage = TokenCount(0, 0, 0.0)
        try:
            if not isinstance(question, dict) or 'question' not in question:
                raise ValueError("Invalid question format")
            if not student_answer.strip():
                raise ValueError("Empty student answer")

            if note is not None:
                context_str = self._extract_note_eval_context(note, question["question"])
            else:
                context_response = await self.context_agent.query_db(
                    subject=subject, question=question["question"], type_req="chat"
                )
                if context_response.error:
                    raise ValueError(f"Failed to get context: {context_response.error}")
                context_str = format_docs(context_response.context)

            subject_rules = get_subject_rules(subject)

            prompt = ChatPromptTemplate.from_messages([
                ("system", _EVAL_SYSTEM),
                ("human", _EVAL_HUMAN),
            ])

            chain = prompt | self._json_llm | StrOutputParser()
            response = await chain.ainvoke({
                "subject": subject,
                "question": question["question"],
                "solution_approach": question.get("solution_approach", question.get("suggested_answer", "")),
                "student_answer": student_answer,
                "context": context_str,
                "grounding_rule": get_grounding_rule(subject),
            })

            try:
                response_str = str(response).strip()
                start_idx = response_str.find('{')
                end_idx = response_str.rfind('}') + 1
                if start_idx == -1 or end_idx <= start_idx:
                    raise ValueError("No JSON object found in response")

                parsed_response = json.loads(response_str[start_idx:end_idx])

                raw_solution = parsed_response.get("correct_solution", [])
                if isinstance(raw_solution, list):
                    correct_solution = [clean_unicode(str(s)) for s in raw_solution]
                else:
                    correct_solution = [clean_unicode(s.strip()) for s in str(raw_solution).split("\\n") if s.strip()]

                token_usage = self._record_token_usage(
                    f"{context_str}\n{subject_rules}",
                    str(parsed_response)
                )

                return {
                    "practice_question": question,
                    "student_answer": student_answer,
                    "is_correct": bool(parsed_response.get("is_correct", False)),
                    "score": float(max(0, min(1, float(parsed_response.get("score", 0))))),
                    "feedback": clean_unicode(str(parsed_response.get("feedback", "No detailed feedback available"))).strip(),
                    "improvement_suggestions": [
                        clean_unicode(str(s))
                        for s in parsed_response.get("improvement_suggestions", ["Review your approach"])
                        if str(s).strip()
                    ] or ["Review your approach"],
                    "correct_solution": correct_solution or ["Solution not provided"],
                    "misconceptions": [
                        clean_unicode(str(m))
                        for m in parsed_response.get("misconceptions", [])
                        if str(m).strip()
                    ],
                    "key_points_missed": [
                        clean_unicode(str(p))
                        for p in parsed_response.get("key_points_missed", [])
                        if str(p).strip()
                    ],
                    "strengths": [
                        clean_unicode(str(s))
                        for s in parsed_response.get("strengths", ["Areas of strength not identified"])
                        if str(s).strip()
                    ] or ["Areas of strength not identified"],
                    "token_usage": str(token_usage),
                }

            except json.JSONDecodeError as e:
                self.logger.error(f"JSON parsing error: {e}\nResponse: {response_str}")
                raise ValueError(f"Invalid JSON format in response: {e}")

        except Exception as e:
            self.logger.error(f"Evaluation error: {e}")
            return {
                "error": str(e),
                "is_correct": False,
                "score": 0,
                "feedback": "Could not evaluate answer due to system error",
                "improvement_suggestions": ["Please try again"],
                "correct_solution": ["Unable to provide solution at this time"],
                "misconceptions": ["Evaluation failed"],
                "key_points_missed": ["Evaluation failed"],
                "strengths": ["Evaluation failed"],
                "token_usage": str(token_usage)
            }

