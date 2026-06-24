"""Tutor chat + note-grounded Q&A; DeepSeek-cached prompts."""

from typing import Any, Dict, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from models import TokenCount
from prompts import (_CHAT_HUMAN, _CHAT_SYSTEM, _NOTECHAT_HUMAN, _NOTECHAT_SRC_HUMAN,
                     _NOTECHAT_SRC_SYSTEM, _NOTECHAT_SYSTEM)
from subject_rules import get_grounding_rule, get_subject_rules
from utils import format_docs, parse_llm_response


class ChatMixin:
    async def chat_response(self, subject: str, question: str,
                            session_id: Optional[str] = None,
                            grade: Optional[int] = None,
                            chat_history_str: str = "") -> Dict[str, Any]:
        """Generate contextual educational responses with chat history support."""
        token_usage = TokenCount(0, 0, 0.0)
        try:
            session = self.sessions.get(session_id) if session_id else None
            if not session:
                session_id = self.sessions.create(subject, grade=grade)
                session = self.sessions.get(session_id)
            elif grade is not None and session.grade is None:
                session.grade = grade

            chat_history = chat_history_str or session.get_recent_context()
            session.add_message("user", question)

            context_response = await self.context_agent.query_db(
                subject=subject, question=question,
                grade=session.grade, unit=None, type_req="chat"
            )

            if context_response.error:
                return {
                    "error": context_response.error,
                    "session_id": session_id,
                    "title": session.title,
                    "conversation_history": session.get_history_as_list(),
                    "current_response": None,
                }

            grade_line = f"Grade: {session.grade}" if session.grade else ""

            prompt = ChatPromptTemplate.from_messages([
                ("system", _CHAT_SYSTEM),
                ("human", _CHAT_HUMAN),
            ])

            chain = prompt | self._json_llm | StrOutputParser()
            response = await chain.ainvoke({
                "context": format_docs(context_response.context),
                "question": question,
                "keypoints": context_response.parsed_answer.get("keypoints", []),
                "chat_history": chat_history,
                "current_title": session.title,
                "subject": session.subject,
                "grade_line": f"\n{grade_line}" if grade_line else "",
                "grounding_rule": get_grounding_rule(subject),
            })

            parsed_response = parse_llm_response(str(response), self.logger)

            if parsed_response.get("out_of_scope", False):
                out_of_scope_msg = parsed_response.get(
                    "answer",
                    "I can only help with Grade 9–12 curriculum subjects. "
                    "Please ask a question related to your studies.",
                )
                session.add_message("assistant", out_of_scope_msg, key_concepts=[])
                token_usage = self._record_token_usage(
                    f"{format_docs(context_response.context)}\n{get_subject_rules(subject)}",
                    str(parsed_response),
                )
                return {
                    "title": session.title,
                    "session_id": session_id,
                    "conversation_history": session.get_history_as_list(),
                    "current_response": {"key_concepts": [], "follow_up_questions": []},
                    "out_of_scope": True,
                    "error": None,
                    "token_usage": str(token_usage),
                }

            if session.title == "New Chat" or parsed_response.get("should_update_title", False):
                new_title = parsed_response.get("title", "")
                if new_title and new_title != session.title:
                    session.title = new_title

            answer = parsed_response.get("answer", "No answer generated")
            key_concepts = parsed_response.get("key_concepts", [])

            scope_result = await self.validation_agent.check_chat_scope(answer, subject)
            if not scope_result.get("in_scope", True):
                self.logger.warning(
                    "Chat scope check failed for session %s: %s",
                    session_id,
                    scope_result.get("reason", ""),
                )
                fallback = (
                    "I can only help with Grade 9–12 curriculum subjects. "
                    "Please ask a question related to your studies."
                )
                session.add_message("assistant", fallback, key_concepts=[])
                token_usage = self._record_token_usage(
                    f"{format_docs(context_response.context)}\n{get_subject_rules(subject)}",
                    str(parsed_response),
                )
                return {
                    "title": session.title,
                    "session_id": session_id,
                    "conversation_history": session.get_history_as_list(),
                    "current_response": {"key_concepts": [], "follow_up_questions": []},
                    "out_of_scope": True,
                    "error": None,
                    "token_usage": str(token_usage),
                }

            session.add_message("assistant", answer, key_concepts=key_concepts)

            token_usage = self._record_token_usage(
                f"{format_docs(context_response.context)}\n{get_subject_rules(subject)}",
                str(parsed_response)
            )

            # Extract grade/unit from retrieved document metadata so the frontend
            # can pre-fill MCQ/Flashcard/Notes when navigating from chat.
            context_grade = None
            context_unit = None
            docs = context_response.context
            if isinstance(docs, list) and docs:
                from collections import Counter
                units = []
                grades = []
                for doc in docs:
                    if not hasattr(doc, "metadata"):
                        continue
                    u = doc.metadata.get("unit")
                    g = doc.metadata.get("grade")
                    if u is not None and str(u).strip():
                        units.append(str(u).strip())
                    if g is not None and str(g).strip():
                        grades.append(str(g).strip())
                if units:
                    context_unit = Counter(units).most_common(1)[0][0]
                if grades:
                    try:
                        context_grade = int(Counter(grades).most_common(1)[0][0])
                    except (ValueError, TypeError):
                        pass

            return {
                "title": session.title,
                "session_id": session_id,
                "conversation_history": session.get_history_as_list(),
                "current_response": {
                    "key_concepts": key_concepts,
                    "follow_up_questions": parsed_response.get("follow_up_questions", []),
                },
                "context_grade": context_grade,
                "context_unit": context_unit,
                "error": None,
                "token_usage": str(token_usage),
            }

        except Exception as e:
            self.logger.error(f"Error generating chat response: {e}")
            return {
                "title": "Error Session",
                "session_id": session_id,
                "conversation_history": session.get_history_as_list() if session else [],
                "current_response": None,
                "error": f"Chat response generation failed: {e}",
                "token_usage": str(token_usage),
            }

    async def note_chat_response(
        self,
        note_content: dict,
        subject: str,
        question: str,
        chat_history_str: str = "",
    ) -> Dict[str, Any]:
        """Answer a question using the note as primary context.

        If the note lacks sufficient detail the agent falls back to the
        curriculum source documents that were used to generate the note.
        """
        token_usage = TokenCount(0, 0, 0.0)
        try:
            context_str = self._extract_note_context(note_content)
            grounding_rule = get_grounding_rule(subject)

            # Pull grade/unit from the note's own metadata for a possible fallback query.
            note_meta = note_content.get("metadata", {})
            grade = note_meta.get("grade")
            unit = note_meta.get("unit")

            prompt_note_only = ChatPromptTemplate.from_messages([
                ("system", _NOTECHAT_SYSTEM),
                ("human", _NOTECHAT_HUMAN),
            ])

            chain = prompt_note_only | self._json_llm | StrOutputParser()
            response = await chain.ainvoke({
                "context": context_str,
                "question": question,
                "chat_history": chat_history_str,
                "subject": subject,
                "grounding_rule": grounding_rule,
            })

            parsed = parse_llm_response(str(response), self.logger)
            token_usage = self._record_token_usage(
                f"{context_str}\n{question}\n{chat_history_str}",
                str(parsed),
            )

            # Fallback: re-answer using curriculum source docs when note context is insufficient.
            if not parsed.get("context_sufficient", True) and grade and unit:
                self.logger.info("[note_chat] note context insufficient — querying source docs")
                fallback = await self.context_agent.query_documents_only(
                    subject=subject,
                    question=question,
                    grade=int(grade) if grade else None,
                    unit=str(unit) if unit else None,
                    type_req="notes",
                )
                if not fallback.error and fallback.context:
                    source_str = format_docs(fallback.context)

                    prompt_with_source = ChatPromptTemplate.from_messages([
                        ("system", _NOTECHAT_SRC_SYSTEM),
                        ("human", _NOTECHAT_SRC_HUMAN),
                    ])

                    fallback_chain = prompt_with_source | self._json_llm | StrOutputParser()
                    fallback_response = await fallback_chain.ainvoke({
                        "note_context": context_str,
                        "source_context": source_str,
                        "question": question,
                        "chat_history": chat_history_str,
                        "subject": subject,
                        "grounding_rule": grounding_rule,
                    })
                    fallback_parsed = parse_llm_response(str(fallback_response), self.logger)
                    token_usage = self._record_token_usage(
                        f"{context_str}\n{source_str}\n{question}\n{chat_history_str}",
                        str(fallback_parsed),
                    )
                    parsed = fallback_parsed

            return {
                "answer": parsed.get("answer", ""),
                "key_concepts": parsed.get("key_concepts", []),
                "follow_up_questions": parsed.get("follow_up_questions", []),
                "error": None,
                "token_usage": str(token_usage),
            }

        except Exception as e:
            self.logger.error(f"Error in note_chat_response: {e}")
            return {
                "answer": "",
                "key_concepts": [],
                "follow_up_questions": [],
                "error": f"Note chat failed: {e}",
                "token_usage": str(token_usage),
            }

