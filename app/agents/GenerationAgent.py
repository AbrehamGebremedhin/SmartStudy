import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import tiktoken
from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_deepseek import ChatDeepSeek

from ContextRefinementAgent import ContextRefinementAgent
from ValidationAgent import ValidationAgent
from models import ChatSession, TokenCount
from mcq_utils import is_test_prep_artifact, redistribute_answer_positions
from session_manager import SessionManager
from subject_rules import (
    STEM_SUBJECTS,
    get_grounding_rule,
    get_mcq_subject_guidance,
    get_subject_focus,
    get_subject_rules,
    presentation_rules,
)
from utils import clean_unicode, format_docs, parse_llm_response, retry_on_none

load_dotenv("./.env")


class GenerationAgent:
    """Generates MCQs, flashcards, chat responses, and study notes using an LLM."""

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

    # ------------------------------------------------------------------
    # Token accounting
    # ------------------------------------------------------------------

    def _count_tokens(self, text: str) -> int:
        return len(self._token_encoder.encode(str(text)))

    def _record_token_usage(self, input_text: str, output_text: str) -> TokenCount:
        inp = self._count_tokens(input_text)
        out = self._count_tokens(output_text)
        cost = (inp * self.COST_PER_1M_INPUT + out * self.COST_PER_1M_OUTPUT) / 1_000_000
        return TokenCount(inp, out, cost)

    # ------------------------------------------------------------------
    # Session management (thin delegation to SessionManager)
    # ------------------------------------------------------------------

    def create_chat_session(self, subject: str, initial_title: str = "New Chat",
                            grade: Optional[int] = None) -> str:
        return self.sessions.create(subject, title=initial_title, grade=grade)

    def get_chat_session(self, session_id: str) -> Optional[ChatSession]:
        return self.sessions.get(session_id)

    def update_session_title(self, session_id: str, new_title: str) -> bool:
        return self.sessions.update_title(session_id, new_title)

    # ------------------------------------------------------------------
    # MCQ generation
    # ------------------------------------------------------------------

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

        return await self.context_agent.query_db(
            subject=subject, question=question,
            grade=grade, unit=unit, type_req="quiz",
        )

    @retry_on_none(max_retries=3)
    async def generate_mcqs(self, subject: str, grade: int, unit: str,
                            num_questions: int = 5, difficulty: str = "hard") -> Dict[str, Any]:
        """Generate multiple choice questions with comprehensive validation."""
        token_usage = TokenCount(0, 0, 0.0)
        try:
            if difficulty not in ["easy", "medium", "hard", "challenging"]:
                difficulty = "medium"

            context_response = await self._retrieve_mcq_context(subject, grade, unit, difficulty)
            if context_response.error:
                return {"error": context_response.error}

            subject_rules = get_subject_rules(subject)
            subject_guidance = get_mcq_subject_guidance(subject) or "- No additional subject-specific rules."
            grounding_rule = get_grounding_rule(subject)

            prompt = PromptTemplate.from_template("""
                Generate {num_questions} {difficulty} multiple choice questions based on the following context.

                {grounding_rule}

                SELF-CONTAINED / NO META-REFERENCE RULE (critical): The student sees ONLY the
                question text, the options, and the `passage` field when present — never the
                source material. This rule applies to the question stem, the options, AND every
                explanation. Therefore:
                - NEVER write "according to the context", "based on the context/passage", "the
                  context states/says", "the context specifically says", "not supported by the
                  context", "as mentioned in the text/table", "in the passage above", "according
                  to the guidelines", "in the matching exercise", "in column A/B", or any phrase
                  that points at material the student cannot see — not even inside explanations.
                - Explanations must justify the answer from general subject knowledge and the
                  question's own content, NOT by citing the source ("the source text gives...").
                - Ground the CONTENT of each question in the provided context, but phrase it as a
                  stand-alone question answerable from the stem (plus `passage`) alone.
                - If a question depends on a reading passage, a quoted sentence, or a vocabulary
                  word in context, you MUST reproduce that text in the `passage` field. If you
                  cannot supply the passage, do not write the question.

                TEST STUDENT SKILLS, NOT ADMINISTRATION OR TEST-PREP TRIVIA: Some source
                material is teacher- or coach-facing — assessment guidelines, marking schemes,
                scoring rubrics, essay-band/level descriptors, answer keys, time/word/file
                limits, exam logistics, study strategies, reading-pace advice. NEVER turn any of
                that into a question (e.g. "what is the maximum length of a sound file", "which
                rubric level shows convincing development", "what does the 4Ps strategy say").
                Only test the student-facing knowledge and skills the material teaches (grammar,
                vocabulary, reading, reasoning, concepts).

                FOUR-OPTION RULE (strict): Every question must have EXACTLY four options labelled
                "A)", "B)", "C)", "D)" — never three, never five. Even if the source uses a
                five-choice format, compress to the four best options with one correct answer.

                OPTION INDEPENDENCE RULE (strict): Options are reshuffled after generation, so no
                option may refer to another option. NEVER write "Both A and B", "Neither A nor C",
                "A and C only", "All of the above", or "None of the above". Each option must be a
                complete, self-contained candidate answer that stands on its own.

                TOPIC LABEL RULE: The `topic` names the concept tested (e.g. "Subject-verb
                agreement", "Synonyms"). It must NOT reference the source's structure — no
                "Word List 1", "Exercise 3", "Column A", "Scoring rubric", page or section numbers.

                Subject Rules:
                {subject_rules}

                Subject-specific question design:
                {subject_guidance}

                Difficulty Level: {difficulty}
                For {difficulty} questions:
                - Use complex, higher-order thinking that requires analysis and synthesis
                - Include questions that test deeper understanding rather than mere recall
                - Incorporate advanced concepts and applications
                - For STEM subjects, include multi-step problems requiring calculation or conceptual reasoning
                - For humanities, include questions requiring critical analysis and evaluation
                - Make distractors (wrong options) more sophisticated and plausible

                UNIQUE TOPICS RULE: Every question must test a different topic. Before writing each
                question, mentally list the topics already used. If a topic is already covered, choose
                a different one. No two questions may share the same topic label.

                Return a JSON object with this exact structure:
                {{"questions": [
                    {{
                        "topic": "specific topic or concept being tested",
                        "passage": "the reading passage, quoted sentence, or sentence-with-blank the question depends on (reading comprehension, inference, vocabulary-in-context, sentence completion); null when the question is fully self-contained in the stem",
                        "question": "question text",
                        "options": ["A) option1", "B) option2", "C) option3", "D) option4"],
                        "correct_answer": "A",
                        "correct_explanations": [
                            "Step 1 of explanation",
                            "Step 2 of explanation",
                            "Final explanation"
                        ],
                        "incorrect_explanations": {{
                            "B": "Reason why B is wrong",
                            "C": "Reason why C is wrong",
                            "D": "Reason why D is wrong"
                        }},
                        "workout_steps": "step-by-step solution if the question involves calculation or multi-step reasoning; null if not applicable",
                        "difficulty": "{difficulty}"
                    }}
                ]}}

                PASSAGE FIELD RULE: Use `passage` only when the question genuinely needs
                accompanying text (a reading passage, a quoted line, or a sentence-completion
                sentence with a "____" blank). For self-contained questions — most grammar,
                vocabulary-definition, and standalone math/factual questions — set it to null.
                When `passage` is present, the question must be answerable from the passage plus
                the stem alone, and every explanation must stay consistent with that passage.

                CRITICAL RULES for incorrect_explanations:
                - The dict must contain ONLY the three wrong option letters.
                - NEVER include the correct_answer key inside incorrect_explanations.
                - If correct_answer is "B", then incorrect_explanations must have keys "A", "C", "D" only.
                - If correct_answer is "C", then incorrect_explanations must have keys "A", "B", "D" only.

                LETTER-INDEPENDENCE RULE (critical): Option positions are reshuffled after
                generation, so the letter labels A/B/C/D are NOT stable. Never reference an option
                by its letter inside correct_explanations or incorrect_explanations. Do not write
                "B is correct", "the answer is C", "unlike option A", or "option D is wrong".
                Refer to options by their content/meaning instead (e.g. "the value 12 is correct
                because..."). The correct_answer field alone communicates the letter.

                Context: {context}

                Areas to focus on: {areas}

                Ensure that:
                1. Each question has a clear specific topic
                2. correct_explanations gives step-by-step reasoning for WHY the correct answer is right
                3. incorrect_explanations explains WHY each wrong option is wrong — never why it is right
                4. All explanations are educational and help students understand the concept
                5. Questions match the {difficulty} difficulty level appropriately
                6. Every statement in correct_explanations AND incorrect_explanations is itself
                   factually accurate — do not introduce biochemical, chemical, or factual errors
                   in the act of explaining why an option is right or wrong
                7. Quantitative self-consistency: if an explanation mentions both a percentage AND a
                   molecule/unit count, verify they match arithmetically before writing them. For
                   example, "26 out of 30" = 87%, not 90%. Never state a percentage and a count
                   that contradict each other in the same explanation.
                8. Quantitative answer options: a bare number or percentage as an option text (e.g.
                   "90%") tests only memorisation. For quantitative questions, include the brief
                   reasoning in the option itself, e.g. "~87%, because oxidative phosphorylation
                   yields ~26 of the ~30 ATP produced from one glucose molecule".
            """)

            chain = prompt | self._json_llm | StrOutputParser()
            invoke_args = {
                "context": format_docs(context_response.context),
                "areas": context_response.parsed_answer.get("areas", []),
                "num_questions": num_questions,
                "subject_rules": subject_rules,
                "subject_guidance": subject_guidance,
                "grounding_rule": grounding_rule,
                "difficulty": difficulty,
            }

            response = await chain.ainvoke(invoke_args)
            parsed_response = parse_llm_response(str(response), self.logger)
            if "error" in parsed_response and "questions" not in parsed_response:
                return None  # triggers @retry_on_none

            validation_result = await self.validation_agent.validate_mcqs(
                parsed_response.get("questions", []),
                context_response.context,
                context_response.parsed_answer.get("areas", [])
            )

            if validation_result["needs_replacement"]:
                replacement_count = len(validation_result["invalid_indices"])
                additional_response = await chain.ainvoke({**invoke_args, "num_questions": replacement_count})
                additional_parsed = parse_llm_response(str(additional_response), self.logger)
                valid_questions = validation_result["valid_mcqs"] + additional_parsed.get("questions", [])
            else:
                valid_questions = validation_result["valid_mcqs"]

            valid_questions = [
                q for q in valid_questions
                if not is_test_prep_artifact(subject, q.get("topic"), q.get("question"), q.get("passage"))
            ]

            # Top-up: filters may have dropped questions below the requested count.
            # Request the shortfall plus a small buffer, apply the same filters, then append.
            shortfall = num_questions - len(valid_questions)
            if shortfall > 0:
                topup_response = await chain.ainvoke({**invoke_args, "num_questions": shortfall + 2})
                topup_parsed = parse_llm_response(str(topup_response), self.logger)
                topup_questions = [
                    q for q in topup_parsed.get("questions", [])
                    if not is_test_prep_artifact(subject, q.get("topic"), q.get("question"), q.get("passage"))
                ]
                valid_questions = valid_questions + topup_questions

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
                str(parsed_response)
            )

            return {
                "questions": valid_questions[:num_questions],
                "error": None,
                "difficulty": difficulty,
                "token_usage": str(token_usage)
            }

        except Exception as e:
            self.logger.error(f"Error generating MCQs: {e}")
            return {"error": f"MCQ generation failed: {e}", "difficulty": difficulty, "token_usage": str(token_usage)}

    # ------------------------------------------------------------------
    # Flashcard generation
    # ------------------------------------------------------------------

    async def generate_flashcards(self, subject: str, num_cards: int = 5,
                                  topic: Optional[str] = None, grade: Optional[int] = None,
                                  unit: Optional[str] = None, difficulty: str = "medium") -> Dict[str, Any]:
        """Generate educational flashcards with validation."""
        token_usage = TokenCount(0, 0, 0.0)
        try:
            if difficulty not in ["easy", "medium", "hard", "challenging"]:
                difficulty = "medium"

            if topic:
                question = f"Generate {difficulty} flashcards for this content on the topic of {topic}"
                context_response = await self.context_agent.query_db(
                    subject=subject, question=question,
                    grade=None, unit=None, type_req="chat"
                )
            elif subject.lower() == "sat":
                question = (
                    f"{difficulty} aptitude material: vocabulary, synonyms and antonyms, "
                    f"analogies, classification, sentence correction, reading and verbal "
                    f"reasoning, and quantitative problem solving"
                )
                context_response = await self.context_agent.query_db(
                    subject=subject, question=question, grade=grade, unit=unit, type_req="quiz"
                )
            else:
                question = f"Generate {difficulty} flashcards for this content"
                context_response = await self.context_agent.query_db(
                    subject=subject, question=question, grade=grade, unit=unit, type_req="quiz"
                )

            if context_response.error:
                return {"error": context_response.error}
            if not context_response.context:
                return {"error": "No relevant documents found"}

            subject_rules = get_subject_rules(subject)
            subject_focus = get_subject_focus(subject) or "- No additional subject focus."
            grounding_rule = get_grounding_rule(subject)
            pres_rules = presentation_rules()

            prompt = PromptTemplate.from_template("""
                Generate {num_cards} {difficulty} flashcards based on the following context.

                {grounding_rule}

                {presentation_rules}

                Subject Rules:
                {subject_rules}

                Subject focus:
                {subject_focus}

                FRONT SIDE RULE (critical): The front must be a single, short prompt — one sentence
                or one clear question, maximum 15 words. It must be instantly scannable. Do NOT write
                multi-sentence questions, comparisons between two things, or embedded context. If a
                concept requires comparison, put the comparison framing on the back, not the front.
                Good examples: "What is the discriminant?", "Define osmosis.", "Formula for kinetic energy?"
                Bad examples: "Compare Goldstein and Thomson and explain how one built on the other."

                BACK SIDE: The back may be as detailed as needed — full explanations, derivations,
                examples, and step-by-step reasoning are all welcome here.

                CARD-FORMAT VARIETY (critical — strictly enforced):
                Do NOT make more than 2 definition cards ("What does X mean?") per 10 cards.
                For SAT, distribute {num_cards} cards roughly as follows (scale proportionally):
                  - 2 vocabulary definitions/meanings
                  - 2 synonyms ("A synonym for PHONEY?") or antonyms ("Opposite of ALACRITY?")
                  - 2 analogies (front: "KEY is to LOCK as ____ is to COMPUTER"; back: answer + relationship name)
                  - 1 classification / odd-one-out (front: "Which does not belong: cat, dog, oak, lion?")
                  - 1 grammar/usage application (front: "Correct this: 'Each of them have left.'")
                  - 1 quantitative (front: "What is 30% of 80?"; back: step-by-step)
                  - remaining: verbal reasoning or reading-inference
                For English, replace analogies with more grammar/usage and reading-inference cards.
                Treat these as targets, not hard quotas — vary the actual examples freely.

                DIFFICULTY — {difficulty}:
                - For STEM: test formulas, derivations, multi-step processes, or conceptual reasoning
                - For humanities: test analytical frameworks, critical perspectives, or key arguments
                - Aim to test understanding and application, not rote memorisation

                ONE-WORD-PER-SET RULE: A vocabulary word, proper noun, or named concept may appear
                as the focus of AT MOST ONE card in the entire set. Before writing each card,
                check all previous cards. If a word already appeared as the quoted/capitalised
                target in a previous card — even in a different format (definition, antonym,
                analogy) — do NOT reuse it; pick a different word entirely.

                DEDUPLICATION RULE (strictly enforced):
                Before writing each new card, mentally list the concepts already covered by all
                previous cards in the set. A new card is a duplicate if:
                  - It tests the same concept, even if the wording differs
                  - It names the same pair of items for comparison (order doesn't matter)
                  - Its topic label differs only in punctuation or capitalisation (e.g. "Foo - Bar"
                    and "Foo: Bar" covering the same content are duplicates)
                  - It uses a different example to reach the same conclusion as another card
                Replace any would-be duplicate with a card on a concept not yet covered.

                TOPIC LABEL RULE: The topic field must be specific — never a bare category.
                Format: "Category: Specific Sub-concept", e.g.:
                  ✓ "Grammar: Present Perfect Tense"
                  ✓ "Punctuation: Oxford Comma"
                  ✓ "Atomic Theory: Rutherford's Nuclear Model"
                  ✗ "Grammar"  ← too generic, rejected
                  ✗ "Punctuation"  ← too generic, rejected

                Return a JSON object with this exact structure:
                {{"flashcards": [
                    {{
                        "front": "short, single-sentence prompt (max 15 words)",
                        "back": "detailed explanation or answer",
                        "topic": "Category: Specific Sub-concept",
                        "difficulty": "{difficulty}"
                    }}
                ]}}

                Context: {context}

                Areas to focus on: {areas}
            """)

            chain = prompt | self._json_llm | StrOutputParser()
            invoke_args = {
                "context": format_docs(context_response.context),
                "areas": context_response.parsed_answer.get("areas", []),
                "num_cards": num_cards,
                "difficulty": difficulty,
                "subject_rules": subject_rules,
                "subject_focus": subject_focus,
                "grounding_rule": grounding_rule,
                "presentation_rules": pres_rules,
            }

            response = await chain.ainvoke(invoke_args)
            parsed_response = parse_llm_response(str(response), self.logger)
            if "error" in parsed_response and "flashcards" not in parsed_response:
                return None  # triggers retry in caller

            validation_result = await self.validation_agent.validate_flashcards(
                parsed_response.get("flashcards", []),
                context_response.context,
                context_response.parsed_answer.get("areas", [])
            )

            if validation_result["needs_replacement"]:
                replacement_count = len(validation_result["invalid_indices"])
                additional_response = await chain.ainvoke({**invoke_args, "num_cards": replacement_count})
                additional_parsed = parse_llm_response(str(additional_response), self.logger)
                valid_cards = validation_result["valid_flashcards"] + additional_parsed.get("flashcards", [])
            else:
                valid_cards = validation_result["valid_flashcards"]

            valid_cards = [
                c for c in valid_cards
                if not is_test_prep_artifact(subject, c.get("front"), c.get("back"), c.get("topic"))
            ]

            # Top-up: filters may have dropped cards below the requested count.
            shortfall = num_cards - len(valid_cards)
            if shortfall > 0:
                topup_response = await chain.ainvoke({**invoke_args, "num_cards": shortfall + 2})
                topup_parsed = parse_llm_response(str(topup_response), self.logger)
                topup_cards = [
                    c for c in topup_parsed.get("flashcards", [])
                    if not is_test_prep_artifact(subject, c.get("front"), c.get("back"), c.get("topic"))
                ]
                valid_cards = valid_cards + topup_cards

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
                str(parsed_response)
            )

            return {
                "flashcards": valid_cards[:num_cards],
                "error": None,
                "difficulty": difficulty,
                "token_usage": str(token_usage)
            }

        except Exception as e:
            self.logger.error(f"Error generating flashcards: {e}")
            return {"error": f"Flashcard generation failed: {e}", "difficulty": difficulty, "token_usage": str(token_usage)}

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

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

            prompt = PromptTemplate.from_template("""
                You are an educational assistant helping a student understand a topic.

                Session context:
                Subject: {subject}{grade_line}

                Previous conversation (may be empty for a new session):
                {chat_history}

                {grounding_rule}

                If the student asks about something genuinely outside the scope of this subject
                and reference material, acknowledge that and steer back to what you can address.

                Using the reference material and the conversation history, answer the student's
                current question clearly and build on anything already discussed.
                Keep the explanation appropriate for the subject and grade level above.
                For new sessions, suggest a descriptive title for the conversation.
                For ongoing sessions, suggest a title update only if the topic has shifted significantly.

                FORMATTING RULES for the answer field:
                - Write in plain prose — no LaTeX delimiters such as \\( \\) or \\[ \\].
                - Express math inline with plain text: ax^2 + bx + c = 0, not \\(ax^2 + bx + c = 0\\).
                - Do not use // or /* */ as comment markers.
                - Newlines in the answer must be real paragraph breaks, not the literal text \\n.

                Reference material: {context}
                Current question: {question}
                Key points to address: {keypoints}
                Current session title: {current_title}

                Respond with this exact JSON structure:
                {{
                    "title": "A clear, specific title describing the conversation topic",
                    "should_update_title": true,
                    "answer": "Your detailed, educational answer here",
                    "key_concepts": ["Key concept 1", "Key concept 2"],
                    "follow_up_questions": ["Related question 1?", "Related question 2?"]
                }}
            """)

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

            if session.title == "New Chat" or parsed_response.get("should_update_title", False):
                new_title = parsed_response.get("title", "")
                if new_title and new_title != session.title:
                    session.title = new_title

            answer = parsed_response.get("answer", "No answer generated")
            key_concepts = parsed_response.get("key_concepts", [])
            session.add_message("assistant", answer, key_concepts=key_concepts)

            token_usage = self._record_token_usage(
                f"{format_docs(context_response.context)}\n{get_subject_rules(subject)}",
                str(parsed_response)
            )

            return {
                "title": session.title,
                "session_id": session_id,
                "conversation_history": session.get_history_as_list(),
                "current_response": {
                    "key_concepts": key_concepts,
                    "follow_up_questions": parsed_response.get("follow_up_questions", []),
                },
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

    # ------------------------------------------------------------------
    # Notes generation
    # ------------------------------------------------------------------

    async def generate_notes(self, subject: str, topic: str, grade: Optional[int] = None,
                             unit: Optional[str] = None, version: str = "1.0") -> Dict[str, Any]:
        """Generate comprehensive study notes with examples and explanations."""
        token_usage = TokenCount(0, 0, 0.0)
        try:
            context_response = await self.context_agent.query_db(
                subject=subject,
                question=f"Generate detailed comprehensive notes about {topic}",
                grade=grade, unit=unit, type_req="notes"
            )

            if context_response.error:
                return {"error": context_response.error}

            subject_rules = get_subject_rules(subject)
            subject_focus = get_subject_focus(subject) or "- No additional subject focus."
            grounding_rule = get_grounding_rule(subject)
            pres_rules = presentation_rules()

            prompt = PromptTemplate.from_template("""
                Generate comprehensive educational notes on the topic based on the provided context.

                {grounding_rule}

                {presentation_rules}

                Subject focus:
                {subject_focus}

                Structure your response in the following detailed JSON format:
                {{
                    "title": "{topic}",
                    "overview": {{
                        "brief_summary": "Concise topic overview",
                        "historical_context": "Historical background and development",
                        "importance": "Why this topic matters",
                        "prerequisites": ["Prerequisite 1", "Prerequisite 2"]
                    }},
                    "learning_objectives": [
                        {{
                            "objective": "What students should learn",
                            "success_criteria": ["Criterion 1", "Criterion 2"]
                        }}
                    ],
                    "key_concepts": [
                        {{
                            "concept": "Main concept name",
                            "detailed_explanation": "In-depth explanation with multiple paragraphs",
                            "sub_concepts": [
                                {{
                                    "name": "Sub-concept name",
                                    "explanation": "Detailed explanation",
                                    "applications": ["Application 1", "Application 2"]
                                }}
                            ],
                            "examples": [
                                {{
                                    "scenario": "Example context",
                                    "demonstration": "Detailed walkthrough",
                                    "analysis": "Why this example matters"
                                }}
                            ],
                            "common_misconceptions": [
                                {{
                                    "misconception": "Common mistake",
                                    "correction": "Proper understanding",
                                    "why_it_matters": "Impact explanation"
                                }}
                            ]
                        }}
                    ],
                    "theoretical_framework": {{
                        "principles": ["Principle 1", "Principle 2"],
                        "theories": [
                            {{
                                "name": "Theory name",
                                "explanation": "Detailed explanation",
                                "applications": ["Application 1", "Application 2"]
                            }}
                        ],
                        "models": ["Model 1", "Model 2"]
                    }},
                    "formulas_and_equations": [
                        {{
                            "formula": "Mathematical expression",
                            "variables": {{
                                "variable_name": "detailed explanation of variable"
                            }},
                            "derivation": "Step-by-step derivation",
                            "applications": ["Application 1", "Application 2"]
                        }}
                    ],
                    "worked_examples": [
                        {{
                            "problem_statement": "Detailed problem description",
                            "approach": ["Step 1", "Step 2"],
                            "solution": "Complete solution with explanations",
                            "common_pitfalls": ["Pitfall 1", "Pitfall 2"],
                            "variations": ["Variation 1", "Variation 2"]
                        }}
                    ],
                    "practice_problems": [
                        {{
                            "question": "Problem statement",
                            "difficulty_level": "Basic/Intermediate/Advanced",
                            "hints": ["Hint 1", "Hint 2"],
                            "solution_approach": "Suggested method"
                        }}
                    ],
                    "real_world_applications": [
                        {{
                            "context": "Application scenario",
                            "explanation": "How the concept applies",
                            "examples": ["Example 1", "Example 2"]
                        }}
                    ],
                    "connections": {{
                        "prerequisites": ["Topic 1", "Topic 2"],
                        "related_topics": ["Related 1", "Related 2"],
                        "future_applications": ["Future use 1", "Future use 2"]
                    }},
                    "review_questions": [
                        {{
                            "question": "Review question 1",
                            "key_points": ["Point 1", "Point 2"],
                            "suggested_answer": "Detailed answer"
                        }},
                        {{
                            "question": "Review question 2",
                            "key_points": ["Point 1", "Point 2"],
                            "suggested_answer": "Detailed answer"
                        }},
                        {{
                            "question": "Review question 3",
                            "key_points": ["Point 1", "Point 2"],
                            "suggested_answer": "Detailed answer"
                        }},
                        {{
                            "question": "Review question 4",
                            "key_points": ["Point 1", "Point 2"],
                            "suggested_answer": "Detailed answer"
                        }},
                        {{
                            "question": "Review question 5",
                            "key_points": ["Point 1", "Point 2"],
                            "suggested_answer": "Detailed answer"
                        }}
                    ]
                }}

                Context: {context}
                Topic: {topic}

                Subject: {subject}
                Subject Rules: {rules}

                Section guidance by subject type:

                formulas_and_equations:
                  - Maths, physics, chemistry: include all relevant equations with derivations
                  - Biology, economics: include only if quantitative formulas appear in the context; otherwise []
                  - Humanities (history, civics, geography, general_business, english): always []
                  - SAT: always []

                worked_examples:
                  - Maths, physics, chemistry: step-by-step problem → solution walkthroughs
                  - Biology: 2+ scenario-based walkthroughs (e.g., "A site is contaminated with mercury — walk through how a bioremediation engineer would approach it step-by-step, including decision points and expected outcomes"). Do NOT leave this as [].
                  - Economics: scenario analysis walkthroughs (policy decision → effects)
                  - SAT: 1-2 step-by-step walkthroughs for the quantitative portion (e.g. a percentage or ratio problem), or for working an analogy/word-relationship; otherwise []
                  - Humanities: always []

                practice_problems:
                  - All science and maths subjects: include at Basic / Intermediate / Advanced levels
                  - SAT: include verbal aptitude items (analogies, synonyms, antonyms, classification) and a few quantitative problems, at Basic / Intermediate / Advanced levels
                  - Humanities: always []

                theoretical_framework.theories:
                  - Derive EVERY theory exclusively from what is present in the provided context.
                  - Do not add theories from outside the context, even if they are broadly related to the subject.
                  - The context comes from the grade-level curriculum; the theories listed must reflect what students at this level are expected to know from that curriculum.
                  - A theory qualifies only if it is directly named, described, or clearly implied in the context passages. If it is not in the context, leave it out.

                Title coherence rule:
                  - The title must reflect ONLY the topics actually covered in key_concepts.
                  - Every subject named in the title must have a corresponding key_concepts entry.
                  - Do not write a broad title and then cover only a subset. Either narrow the title
                    to match what you cover, or add key_concepts entries for every topic in the title.

                Chemical/biological accuracy rule:
                  - When describing transformation processes (e.g., converting a toxic compound to
                    another form), use precise relative language: "less toxic", "less bioavailable",
                    "reduced toxicity", or "changed to a less harmful form".
                  - NEVER use "nontoxic" or "harmless" for a product that still poses hazards in
                    any form. This applies even when the product is less dangerous than the starting
                    material. Use "less toxic" or "less bioavailable" instead.

                Internal consistency rule:
                  - Before finalising, check that every numerical value, yield, or quantity that
                    appears more than once across sections is either identical or explicitly reconciled.
                  - If a quantity genuinely varies by condition (e.g., ATP yield differs by shuttle
                    mechanism, or reaction rate differs by temperature), DO NOT state the different
                    values in isolation. Instead, present them together with a clear explanation of
                    what causes the difference. Turn the variation into a teaching point, not a
                    contradiction.
                  - Example: if one section gives "36–38 ATP" and a worked example gives "32 ATP",
                    the worked example must state which shuttle or condition produces 32 and why that
                    differs from the theoretical maximum.

                review_questions:
                  - Generate EXACTLY 5 review questions covering different aspects of the topic.
                  - Each question must have specific key_points (at least 2) and a detailed suggested_answer.
                  - Vary the questions across recall, comprehension, and application levels.

                Ensure to:
                1. Provide detailed explanations for each key concept — multiple paragraphs per concept
                2. Include multiple examples with varying difficulty levels
                3. Address common misconceptions and mistakes
                4. Connect theoretical knowledge with practical applications
                5. Include both basic and advanced content where appropriate
                6. Do not abbreviate or placeholder sections — write full content for every field
            """)

            chain = prompt | self._json_llm | StrOutputParser()
            response = await chain.ainvoke({
                "context": format_docs(context_response.context),
                "topic": topic,
                "subject": subject,
                "rules": subject_rules,
                "subject_focus": subject_focus,
                "grounding_rule": grounding_rule,
                "presentation_rules": pres_rules,
            })

            parsed_response = parse_llm_response(str(response), self.logger)

            required_sections = ["title", "overview", "learning_objectives", "key_concepts", "real_world_applications"]
            if subject.lower() in STEM_SUBJECTS:
                required_sections += ["worked_examples", "practice_problems"]

            if not all(key in parsed_response for key in required_sections):
                raise ValueError("Generated notes missing required sections")

            notes_validation = await self.validation_agent.validate_notes(
                parsed_response, context_response.context
            )
            if not notes_validation.get("is_valid", True):
                self.logger.warning(f"Notes validation flagged content: {notes_validation.get('reason', '')}")

            parsed_response["metadata"] = {
                "subject": subject,
                "topic": topic,
                "grade": grade,
                "unit": unit,
                "generated_at": datetime.now().isoformat(),
                "complexity_level": "comprehensive",
                "estimated_study_time": "45-60 minutes",
                "version": version,
                "is_valid": notes_validation.get("is_valid", True),
                "validation_note": notes_validation.get("reason", ""),
            }

            token_usage = self._record_token_usage(
                f"{format_docs(context_response.context)}\n{subject_rules}",
                str(parsed_response)
            )

            return {"notes": parsed_response, "error": None, "token_usage": str(token_usage)}

        except Exception as e:
            self.logger.error(f"Error generating notes: {e}")
            return {"error": f"Notes generation failed: {e}", "token_usage": str(token_usage)}

    # ------------------------------------------------------------------
    # Answer evaluation
    # ------------------------------------------------------------------

    def _extract_note_context(self, note: Dict[str, Any], question_text: str) -> str:
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
                context_str = self._extract_note_context(note, question["question"])
            else:
                context_response = await self.context_agent.query_db(
                    subject=subject, question=question["question"], type_req="chat"
                )
                if context_response.error:
                    raise ValueError(f"Failed to get context: {context_response.error}")
                context_str = format_docs(context_response.context)

            subject_rules = get_subject_rules(subject)

            prompt = PromptTemplate.from_template("""
                Evaluate this student's answer.

                SUBJECT: {subject}
                QUESTION: {question}
                STUDENT'S ANSWER: {student_answer}
                EXPECTED APPROACH: {solution_approach}
                CONTEXT: {context}

                Your task is to evaluate the student's answer and provide feedback directly to the student.

                {grounding_rule}
                Keep the correct solution and feedback consistent with the expected approach above.

                CRITICAL RULES:
                - Address the student directly ("Your answer...", "You correctly...", "You missed...").
                - Evaluate ONLY whether the student's answer is correct for the given question.
                - NEVER mention the context, the RAG system, or comment on the quality or relevance
                  of any background material. The context is a private reference — treat it as invisible.
                - Do not say things like "the provided context...", "based on the context...", or
                  "the context seems unrelated". The student must never know the context exists.

                Return this exact JSON structure:
                {{
                    "is_correct": true,
                    "score": 0.85,
                    "feedback": "Your solution is mostly correct. You correctly factored the equation...",
                    "improvement_suggestions": [
                        "Show your intermediate steps",
                        "Explain why you chose factoring"
                    ],
                    "correct_solution": [
                        "Step 1: Rearrange to standard form: x^2 - 5x + 6 = 0",
                        "Step 2: Factor: (x-2)(x-3) = 0",
                        "Step 3: Solve: x = 2 or x = 3"
                    ],
                    "misconceptions": [],
                    "key_points_missed": [],
                    "strengths": [
                        "Correct factoring technique",
                        "Arrived at right answer"
                    ]
                }}

                Rules:
                1. Keep all JSON fields
                2. Score must be between 0 and 1
                3. correct_solution MUST be a JSON array of strings, one step per element — never a single string with \\n
                4. misconceptions and key_points_missed MUST be empty arrays [] when there is nothing to report — never use filler strings like "None identified"
                5. improvement_suggestions and strengths must each have at least one item
                6. Feedback must be specific and actionable, addressed to the student
                7. Maintain proper JSON format
            """)

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

# Example usage
async def _main():
    agent = GenerationAgent()

    # Generate MCQs
    mcqs = await agent.generate_mcqs(
        subject="sat",
        grade=12,
        unit="3",
        num_questions=10
    )
    print("MCQs:", json.dumps(mcqs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_main())

    # notes = agent.generate_notes(
    #     subject="biology",
    #     topic="ATP synthesis in cellular respiration",
    #     grade=12,
    #     unit="3"
    # )
    # print("Notes:", json.dumps(notes, indent=2, ensure_ascii=False))

    # # Generate Flashcards
    # flashcards = agent.generate_flashcards(
    #     subject="sat",
    #     grade=9,
    #     unit="3",
    #     num_cards=20
    # )
    # print("Flashcards:", json.dumps(flashcards, indent=2, ensure_ascii=False))

    # # Generate Flashcards with topic
    # flashcards_with_topic = agent.generate_flashcards(
    #     subject="english",
    #     num_cards=10,
    #     topic="Verb strings identification"
    # )
    # print("Flashcards with Topic:", json.dumps(flashcards_with_topic, indent=2, ensure_ascii=False))

    # Test chat functionality
    # session_id = agent.create_chat_session("maths", "Math Help")

    # questions = [
    #     "Can you explain what a quadratic equation is?",
    # ]

    # for question in questions:
    #     response = agent.chat_response("maths", question, session_id)
    #     print("Response: ", json.dumps(response, indent=2, ensure_ascii=False))

    # Test answer evaluation
    # practice_question = {
    #     "question": "Solve the quadratic equation: x^2 - 5x + 6 = 0",
    #     "solution_approach": "Use factoring or quadratic formula to find x = 2 and x = 3"
    # }

    # student_answer = "x = 2 or x = 3"

    # evaluation = agent.evaluate_practice_answer(
    #     subject="maths",
    #     question=practice_question,
    #     student_answer=student_answer
    # )
    # print("\nAnswer Evaluation:", json.dumps(evaluation, indent=2, ensure_ascii=False))
