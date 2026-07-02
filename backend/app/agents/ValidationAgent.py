import os
import logging
from typing import Dict, List, Any
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import json
import tiktoken

from models import TokenCount
from prompts import (_CHAT_SCOPE_HUMAN, _CHAT_SCOPE_SYSTEM, _COVERAGE_HUMAN, _COVERAGE_SYSTEM,
                     _FLASHCARD_VALIDATE_HUMAN, _FLASHCARD_VALIDATE_SYSTEM, _MCQ_VALIDATE_HUMAN,
                     _MCQ_VALIDATE_SYSTEM, _NOTES_VALIDATE_HUMAN, _NOTES_VALIDATE_SYSTEM)
from utils import format_docs as _format_docs


class ValidationAgent:
    def __init__(self):
        load_dotenv("./.env")
        self.logger = logging.getLogger(__name__)
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment")

        # temperature 0: validation is a judgment/classification task (valid or not), not
        # creative generation — deterministic output is strictly better here.
        self.llm = ChatDeepSeek(model="deepseek-v4-flash", api_key=api_key, temperature=0)
        self._json_llm = self.llm.bind(response_format={"type": "json_object"})
        # NOTE: tiktoken's gpt-3.5-turbo encoding is an APPROXIMATION for DeepSeek, which
        # uses a different tokenizer. Token counts and cost estimates are indicative only.
        self.token_counter = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.COST_PER_1M_INPUT = 0.14   # DeepSeek-V4-Flash
        self.COST_PER_1M_OUTPUT = 0.28  # DeepSeek-V4-Flash

    def count_tokens(self, text: str) -> int:
        return len(self.token_counter.encode(str(text)))

    def record_token_usage(self, input_text: str, output_text: str) -> TokenCount:
        """Return per-call token usage; does not accumulate across requests."""
        input_tokens = self.count_tokens(input_text)
        output_tokens = self.count_tokens(output_text)
        cost = (
            (input_tokens * self.COST_PER_1M_INPUT / 1_000_000) +
            (output_tokens * self.COST_PER_1M_OUTPUT / 1_000_000)
        )
        return TokenCount(input_tokens, output_tokens, cost)

    async def _run_chain(self, prompt: "PromptTemplate | ChatPromptTemplate", inputs: dict) -> str:
        if "context" in inputs:
            inputs = {**inputs, "context": _format_docs(inputs["context"])}
        chain = prompt | self._json_llm | StrOutputParser()
        return await chain.ainvoke(inputs)

    async def validate_mcqs(self, mcqs: List[Dict], context) -> Dict[str, Any]:
        _zero = TokenCount(0, 0, 0.0)
        if not mcqs:
            return {"valid_mcqs": [], "invalid_indices": [], "needs_replacement": False,
                    "token_usage": str(_zero)}

        # --- structural checks (no API call) ---
        struct_invalid: set = set()
        seen_questions: set = set()
        for i, mcq in enumerate(mcqs):
            required = ["topic", "question", "options", "correct_answer",
                        "correct_explanations", "incorrect_explanations"]
            if not all(k in mcq for k in required):
                struct_invalid.add(i); continue
            if not mcq["topic"] or not isinstance(mcq["topic"], str):
                struct_invalid.add(i); continue
            if not isinstance(mcq["correct_explanations"], list) or \
               not isinstance(mcq["incorrect_explanations"], dict):
                struct_invalid.add(i); continue
            # The app assumes a fixed four-option A-D format everywhere (answer
            # redistribution, option labelling). Reject anything else so it is regenerated.
            if not isinstance(mcq["options"], list) or len(mcq["options"]) != 4:
                struct_invalid.add(i); continue
            options = [opt[0] for opt in mcq["options"]]
            incorrect_opts = [o for o in options if o != mcq["correct_answer"]]
            if not all(o in mcq["incorrect_explanations"] for o in incorrect_opts):
                struct_invalid.add(i); continue
            if mcq["question"] in seen_questions:
                struct_invalid.add(i); continue
            seen_questions.add(mcq["question"])

        candidates = [i for i in range(len(mcqs)) if i not in struct_invalid]
        if not candidates:
            return {
                "valid_mcqs": [],
                "invalid_indices": list(struct_invalid),
                "needs_replacement": True,
                "token_usage": str(_zero),
            }

        # --- single batch LLM call for remaining candidates ---
        # Include the passage when a question carries one so the validator judges
        # passage-dependent reading/vocab questions on their own terms, not as if the
        # stem alone had to be answerable.
        def _line(i: int) -> str:
            mcq = mcqs[i]
            passage = mcq.get("passage")
            base = f"{i}. Q: {mcq['question']} | Answer: {mcq['correct_answer']}"
            if passage and str(passage).strip():
                return f"{base} | Passage: {str(passage).strip()}"
            return base

        numbered = "\n".join(_line(i) for i in candidates)
        prompt = ChatPromptTemplate.from_messages([
            ("system", _MCQ_VALIDATE_SYSTEM),
            ("human", _MCQ_VALIDATE_HUMAN),
        ])
        llm_invalid: set = set()
        token_usage = _zero
        try:
            response = await self._run_chain(prompt, {
                "context": context,
                "questions": numbered,
            })
            parsed = json.loads(str(response))
            for entry in parsed.get("results", []):
                if not entry.get("is_valid", True):
                    llm_invalid.add(int(entry["index"]))
            token_usage = self.record_token_usage(numbered, str(parsed))
        except Exception:
            pass  # on batch failure keep all candidates as valid

        invalid_indices = sorted(struct_invalid | llm_invalid)
        return {
            "valid_mcqs": [mcq for i, mcq in enumerate(mcqs) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(token_usage),
        }

    async def validate_flashcards(self, flashcards: List[Dict], context) -> Dict[str, Any]:
        _zero = TokenCount(0, 0, 0.0)
        if not flashcards:
            return {"valid_flashcards": [], "invalid_indices": [], "needs_replacement": False,
                    "token_usage": str(_zero)}

        # --- structural checks (no API call) ---
        struct_invalid: set = set()
        seen_fronts: set = set()
        for i, card in enumerate(flashcards):
            if not all(k in card for k in ["front", "back", "topic"]):
                struct_invalid.add(i); continue
            if card["front"] in seen_fronts:
                struct_invalid.add(i); continue
            seen_fronts.add(card["front"])

        candidates = [i for i in range(len(flashcards)) if i not in struct_invalid]
        if not candidates:
            return {
                "valid_flashcards": [],
                "invalid_indices": list(struct_invalid),
                "needs_replacement": True,
                "token_usage": str(_zero),
            }

        # --- single batch LLM call for remaining candidates ---
        numbered = "\n".join(
            f"{i}. Front: {flashcards[i]['front']} | Topic: {flashcards[i]['topic']}"
            for i in candidates
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", _FLASHCARD_VALIDATE_SYSTEM),
            ("human", _FLASHCARD_VALIDATE_HUMAN),
        ])
        llm_invalid: set = set()
        token_usage = _zero
        try:
            response = await self._run_chain(prompt, {
                "context": context,
                "cards": numbered,
            })
            parsed = json.loads(str(response))
            for entry in parsed.get("results", []):
                if not entry.get("is_valid", True):
                    llm_invalid.add(int(entry["index"]))
            token_usage = self.record_token_usage(numbered, str(parsed))
        except Exception:
            pass  # on batch failure keep all candidates as valid

        invalid_indices = sorted(struct_invalid | llm_invalid)
        return {
            "valid_flashcards": [card for i, card in enumerate(flashcards) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(token_usage),
        }

    async def check_chat_scope(self, answer: str, subject: str) -> Dict[str, Any]:
        """
        Fast scope check: confirm the assistant's chat answer is on-topic for the
        given curriculum subject.  Fails open (returns in_scope=True) on errors so
        that a validation hiccup never silently swallows a legitimate response.
        """
        _zero = TokenCount(0, 0, 0.0)
        if not answer or not answer.strip():
            return {"in_scope": False, "reason": "Empty answer", "token_usage": str(_zero)}

        prompt = ChatPromptTemplate.from_messages([
            ("system", _CHAT_SCOPE_SYSTEM),
            ("human", _CHAT_SCOPE_HUMAN),
        ])

        try:
            response = await self._run_chain(prompt, {"subject": subject, "answer": answer})
            result = json.loads(str(response))
            token_usage = self.record_token_usage(f"{subject}\n{answer}", str(result))
            return {
                "in_scope": result.get("in_scope", True),
                "reason": result.get("reason", ""),
                "token_usage": str(token_usage),
            }
        except Exception:
            return {"in_scope": True, "reason": "Scope check failed — assuming in scope", "token_usage": str(_zero)}

    async def validate_notes(self, notes: Dict[str, Any], context) -> Dict[str, Any]:
        _zero = TokenCount(0, 0, 0.0)
        prompt = ChatPromptTemplate.from_messages([
            ("system", _NOTES_VALIDATE_SYSTEM),
            ("human", _NOTES_VALIDATE_HUMAN),
        ])

        try:
            response = await self._run_chain(prompt, {
                "context": context,
                "notes": json.dumps(notes),
            })
            validation = json.loads(str(response))
            token_usage = self.record_token_usage(
                f"{_format_docs(context)}\n{json.dumps(notes)}",
                str(validation)
            )
            # Fail open (consistent with check_chat_scope): assume valid unless the
            # model explicitly says otherwise.
            is_valid = validation.get("is_valid", True)
            return {
                "is_valid": is_valid,
                "reason": validation.get("reason", ""),
                "needs_regeneration": not is_valid,
                "token_usage": str(token_usage)
            }
        except Exception:
            return {
                "is_valid": True,
                "reason": "Validation parsing failed - assuming valid",
                "needs_regeneration": False,
                "token_usage": str(_zero)
            }

    async def validate_coverage_from_context(
        self,
        topic: str,
        context,
        subject: str,
        grade: "int | None",
        unit: "str | None",
    ) -> "Dict[str, Any]":
        """Check topic coverage directly from retrieved documents — no pre-extracted key_concepts needed.

        Single LLM call that replaces the old two-step query_db(notes) + validate_topic_coverage
        flow, cutting one sequential LLM round-trip from the notes pipeline.
        Fails open so validation hiccups never block legitimate requests.
        """
        _zero = TokenCount(0, 0, 0.0)

        grade_unit_str = ""
        if grade is not None:
            grade_unit_str += f" Grade {grade}"
        if unit is not None:
            grade_unit_str += f" Unit {unit}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", _COVERAGE_SYSTEM),
            ("human", _COVERAGE_HUMAN),
        ])

        try:
            response = await self._run_chain(prompt, {
                "topic": topic,
                "subject": subject,
                "grade_unit": grade_unit_str,
                "context": context,
            })
            result = json.loads(str(response))
            token_usage = self.record_token_usage(
                f"{topic}\n{subject}\n{_format_docs(context)}",
                str(result),
            )
            return {
                "is_covered": result.get("is_covered", True),
                "available_topics": result.get("available_topics", []),
                "reason": result.get("reason", ""),
                "token_usage": str(token_usage),
            }
        except Exception:
            return {"is_covered": True, "available_topics": [], "token_usage": str(_zero)}
