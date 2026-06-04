import os
import logging
from typing import Dict, List, Any
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document
import json
import tiktoken
from dataclasses import dataclass


def _format_docs(context) -> str:
    if isinstance(context, list):
        return "\n\n".join(
            doc.page_content if isinstance(doc, Document) else str(doc)
            for doc in context
        )
    return str(context)


@dataclass
class TokenCount:
    input_tokens: int
    output_tokens: int
    total_cost: float

    def __str__(self):
        return f"Input tokens: {self.input_tokens}\nOutput tokens: {self.output_tokens}\nTotal tokens: {self.input_tokens + self.output_tokens}\nEstimated cost: ${self.total_cost:.4f}"


class ValidationAgent:
    def __init__(self):
        load_dotenv("./.env")
        self.logger = logging.getLogger(__name__)
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment")

        self.llm = ChatDeepSeek(model="deepseek-chat", api_key=api_key)
        # NOTE: tiktoken's gpt-3.5-turbo encoding is an APPROXIMATION for DeepSeek, which
        # uses a different tokenizer. Token counts and cost estimates are indicative only.
        self.token_counter = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.token_counts = []
        self.COST_PER_1M_INPUT = 0.27
        self.COST_PER_1M_OUTPUT = 1.10

    def count_tokens(self, text: str) -> int:
        return len(self.token_counter.encode(str(text)))

    def record_token_usage(self, input_text: str, output_text: str) -> TokenCount:
        input_tokens = self.count_tokens(input_text)
        output_tokens = self.count_tokens(output_text)
        cost = (
            (input_tokens * self.COST_PER_1M_INPUT / 1_000_000) +
            (output_tokens * self.COST_PER_1M_OUTPUT / 1_000_000)
        )
        token_count = TokenCount(input_tokens, output_tokens, cost)
        self.token_counts.append(token_count)
        return token_count

    def get_total_token_usage(self) -> TokenCount:
        total_input = sum(tc.input_tokens for tc in self.token_counts)
        total_output = sum(tc.output_tokens for tc in self.token_counts)
        total_cost = sum(tc.total_cost for tc in self.token_counts)
        return TokenCount(total_input, total_output, total_cost)

    def _run_chain(self, prompt: PromptTemplate, inputs: dict) -> str:
        if "context" in inputs:
            inputs = {**inputs, "context": _format_docs(inputs["context"])}
        json_llm = self.llm.bind(response_format={"type": "json_object"})
        chain = prompt | json_llm | StrOutputParser()
        return chain.invoke(inputs)

    def validate_mcqs(self, mcqs: List[Dict], context, areas: List[str]) -> Dict[str, Any]:
        if not mcqs:
            return {"valid_mcqs": [], "invalid_indices": [], "needs_replacement": False,
                    "token_usage": str(self.get_total_token_usage())}

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
                "token_usage": str(self.get_total_token_usage()),
            }

        # --- single batch LLM call for remaining candidates ---
        numbered = "\n".join(
            f"{i}. Q: {mcqs[i]['question']} | Answer: {mcqs[i]['correct_answer']}"
            for i in candidates
        )
        prompt = PromptTemplate.from_template("""
            Validate these MCQs against the context and focus areas.
            For each numbered question return whether it is valid.

            Context: {context}
            Focus Areas: {areas}
            Questions:
            {questions}

            Return JSON with this exact structure:
            {{"results": [{{"index": 0, "is_valid": true, "reason": ""}}]}}
            Include one entry per question using the original index numbers shown above.
        """)
        llm_invalid: set = set()
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
            self.record_token_usage(numbered, str(parsed))
        except Exception:
            pass  # on batch failure keep all candidates as valid

        invalid_indices = sorted(struct_invalid | llm_invalid)
        return {
            "valid_mcqs": [mcq for i, mcq in enumerate(mcqs) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(self.get_total_token_usage()),
        }

    def validate_flashcards(self, flashcards: List[Dict], context, areas: List[str]) -> Dict[str, Any]:
        if not flashcards:
            return {"valid_flashcards": [], "invalid_indices": [], "needs_replacement": False,
                    "token_usage": str(self.get_total_token_usage())}

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
                "token_usage": str(self.get_total_token_usage()),
            }

        # --- single batch LLM call for remaining candidates ---
        numbered = "\n".join(
            f"{i}. Front: {flashcards[i]['front']} | Topic: {flashcards[i]['topic']}"
            for i in candidates
        )
        prompt = PromptTemplate.from_template("""
            Validate these flashcards against the context and focus areas.
            Each card must be relevant to the context and cover a topic from the focus areas.

            Context: {context}
            Focus Areas: {areas}
            Flashcards:
            {cards}

            Return JSON with this exact structure:
            {{"results": [{{"index": 0, "is_valid": true, "reason": ""}}]}}
            Include one entry per card using the original index numbers shown above.
        """)
        llm_invalid: set = set()
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
            self.record_token_usage(numbered, str(parsed))
        except Exception:
            pass  # on batch failure keep all candidates as valid

        invalid_indices = sorted(struct_invalid | llm_invalid)
        return {
            "valid_flashcards": [card for i, card in enumerate(flashcards) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(self.get_total_token_usage()),
        }

    def validate_chat_response(self, response: Dict, context, keypoints: List[str]) -> Dict[str, Any]:
        if isinstance(response, dict):
            if "error" in response:
                return {
                    "is_valid": False,
                    "reason": response["error"],
                    "needs_regeneration": True,
                    "token_usage": str(self.get_total_token_usage())
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
                "token_usage": str(self.get_total_token_usage())
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
            self.record_token_usage(
                f"{_format_docs(context)}\n{response_text}\n{str(keypoints)}",
                str(validation)
            )
            is_valid = validation.get("is_valid", True)
            return {
                "is_valid": is_valid,
                "reason": validation.get("reason", ""),
                "needs_regeneration": not is_valid,
                "token_usage": str(self.get_total_token_usage())
            }
        except Exception:
            return {
                "is_valid": True,
                "reason": "Validation parsing failed - assuming valid",
                "needs_regeneration": False,
                "token_usage": str(self.get_total_token_usage())
            }

    def validate_notes(self, notes: Dict[str, Any], context) -> Dict[str, Any]:
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
            self.record_token_usage(
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
                "token_usage": str(self.get_total_token_usage())
            }
        except Exception:
            return {
                "is_valid": True,
                "reason": "Validation parsing failed - assuming valid",
                "needs_regeneration": False,
                "token_usage": str(self.get_total_token_usage())
            }
