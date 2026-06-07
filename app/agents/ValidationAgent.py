import os
import logging
from typing import Dict, List, Any
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import json
import tiktoken

from models import TokenCount
from utils import format_docs as _format_docs


class ValidationAgent:
    def __init__(self):
        load_dotenv("./.env")
        self.logger = logging.getLogger(__name__)
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment")

        self.llm = ChatDeepSeek(model="deepseek-v4-flash", api_key=api_key)
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

    def _run_chain(self, prompt: PromptTemplate, inputs: dict) -> str:
        if "context" in inputs:
            inputs = {**inputs, "context": _format_docs(inputs["context"])}
        json_llm = self.llm.bind(response_format={"type": "json_object"})
        chain = prompt | json_llm | StrOutputParser()
        return chain.invoke(inputs)

    def validate_mcqs(self, mcqs: List[Dict], context, areas: List[str]) -> Dict[str, Any]:
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
        prompt = PromptTemplate.from_template("""
            Validate these MCQs for the subject area represented by the context and focus areas.
            For each numbered question return whether it is valid.

            A question is VALID when it is on-topic for this subject area, self-contained, has
            exactly one defensible correct answer, and is answerable from its own stem plus its
            Passage (when one is shown). The question need NOT quote the context verbatim —
            vocabulary, analogy, reasoning and reading questions may use their own wording and
            their own passage, as long as they stay within the subject's level and topics.

            Mark a question INVALID if any of these hold:
            - it is off-topic for the subject;
            - it has no correct answer, or more than one defensible correct answer;
            - it depends on a reading passage / quoted line / vocabulary-in-context word that is
              NOT supplied in its Passage;
            - it tests test-administration or test-prep material rather than an academic skill —
              e.g. scoring rubrics, essay-band/level descriptors, marking schemes, answer keys,
              study strategies, reading-pace advice, time/word/file limits, or exam logistics;
            - an option refers to another option ("Both A and B", "All of the above", etc.).

            Context: {context}
            Focus Areas: {areas}
            Questions:
            {questions}

            Return JSON with this exact structure:
            {{"results": [{{"index": 0, "is_valid": true, "reason": ""}}]}}
            Include one entry per question using the original index numbers shown above.
        """)
        llm_invalid: set = set()
        token_usage = _zero
        try:
            response = self._run_chain(prompt, {
                "context": context,
                "areas": areas,
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

    def validate_flashcards(self, flashcards: List[Dict], context, areas: List[str]) -> Dict[str, Any]:
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
        prompt = PromptTemplate.from_template("""
            Validate these flashcards for the subject area represented by the context and focus
            areas. A card is VALID when it is on-topic for this subject area and teaches a clear,
            correct piece of knowledge or skill. The card need NOT quote the context verbatim —
            vocabulary, analogy, grammar and reasoning cards may use their own wording as long as
            they stay within the subject's level and topics.

            Mark a card INVALID if it is off-topic for the subject, factually wrong, or — instead
            of teaching an academic skill — describes how a test works or how to study for it.
            This includes study acronyms or mnemonics (BLANKS, READING, 4Ps), essay scoring
            levels/bands/rubrics ("characteristics of a Level 6 essay"), lists of passage types
            or question categories, test-section breakdowns, reading-pace advice, marking schemes,
            and exam logistics. A card whose answer is a fact ABOUT the exam is INVALID.

            Context: {context}
            Focus Areas: {areas}
            Flashcards:
            {cards}

            Return JSON with this exact structure:
            {{"results": [{{"index": 0, "is_valid": true, "reason": ""}}]}}
            Include one entry per card using the original index numbers shown above.
        """)
        llm_invalid: set = set()
        token_usage = _zero
        try:
            response = self._run_chain(prompt, {
                "context": context,
                "areas": areas,
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

    def validate_chat_response(self, response: Dict, context, keypoints: List[str]) -> Dict[str, Any]:
        _zero = TokenCount(0, 0, 0.0)
        if isinstance(response, dict):
            if "error" in response:
                return {
                    "is_valid": False,
                    "reason": response["error"],
                    "needs_regeneration": True,
                    "token_usage": str(_zero)
                }
            if "response" in response:
                if isinstance(response["response"], dict):
                    response_text = response["response"].get("response", "")
                else:
                    response_text = str(response["response"])
            else:
                response_text = str(response)
        else:
            response_text = str(response)

        if not response_text.strip():
            return {
                "is_valid": False,
                "reason": "Empty response",
                "needs_regeneration": True,
                "token_usage": str(_zero)
            }

        prompt = PromptTemplate.from_template("""
            Evaluate this educational response based on these criteria:
            1. Addresses key points: {keypoints}
            2. Accurate per context
            3. Clear and well-structured
            4. Contains substantive information
            5. Uses appropriate tone and language level

            Context: {context}
            Response: {response}

            Return JSON: {{"is_valid": boolean, "reason": "explanation if invalid"}}
        """)

        try:
            validation_response = self._run_chain(prompt, {
                "context": context,
                "keypoints": keypoints,
                "response": response_text,
            })
            validation = json.loads(str(validation_response))
            token_usage = self.record_token_usage(
                f"{_format_docs(context)}\n{response_text}\n{str(keypoints)}",
                str(validation)
            )
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

    def validate_notes(self, notes: Dict[str, Any], context) -> Dict[str, Any]:
        _zero = TokenCount(0, 0, 0.0)
        prompt = PromptTemplate.from_template("""
            Validate these educational notes based on the following criteria:
            1. Content accuracy matches context
            2. Examples are relevant and clear
            3. Explanations are thorough but concise
            4. All required sections are present and complete

            Context: {context}
            Notes: {notes}

            Return JSON: {{"is_valid": boolean, "reason": "explanation if invalid"}}
        """)

        try:
            response = self._run_chain(prompt, {
                "context": context,
                "notes": json.dumps(notes),
            })
            validation = json.loads(str(response))
            token_usage = self.record_token_usage(
                f"{_format_docs(context)}\n{json.dumps(notes)}",
                str(validation)
            )
            # Fail open (consistent with validate_chat_response): assume valid unless the
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

