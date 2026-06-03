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
        chain = prompt | self.llm | StrOutputParser()
        return chain.invoke(inputs)

    def validate_mcqs(self, mcqs: List[Dict], context, areas: List[str]) -> Dict[str, Any]:
        invalid_indices = []
        for i, mcq in enumerate(mcqs):
            if not all(key in mcq for key in ["topic", "question", "options", "correct_answer", "correct_explanations", "incorrect_explanations"]):
                invalid_indices.append(i)
                continue

            if not mcq["topic"] or not isinstance(mcq["topic"], str):
                invalid_indices.append(i)
                continue

            if not isinstance(mcq["correct_explanations"], list) or not isinstance(mcq["incorrect_explanations"], dict):
                invalid_indices.append(i)
                continue

            options = [opt[0] for opt in mcq["options"]]
            correct_opt = mcq["correct_answer"]
            incorrect_opts = [opt for opt in options if opt != correct_opt]
            if not all(opt in mcq["incorrect_explanations"] for opt in incorrect_opts):
                invalid_indices.append(i)
                continue

            if any(mcq["question"] == other["question"] for other in mcqs[:i]):
                invalid_indices.append(i)
                continue

            prompt = PromptTemplate.from_template("""
                Validate if this MCQ is valid based on the following criteria:
                1. Question is relevant to the context
                2. Question covers one of the focus areas
                3. Correct answer is clearly correct
                4. Options are distinct and reasonable

                Context: {context}
                Focus Areas: {areas}
                Question: {question}
                Options: {options}
                Correct Answer: {answer}

                Return JSON: {{"is_valid": boolean, "reason": "explanation if invalid"}}
            """)

            try:
                response = self._run_chain(prompt, {
                    "context": context,
                    "areas": areas,
                    "question": mcq["question"],
                    "options": mcq["options"],
                    "answer": mcq["correct_answer"],
                })
                validation = json.loads(str(response))
                if not validation.get("is_valid", False):
                    invalid_indices.append(i)
                self.record_token_usage(
                    f"{_format_docs(context)}\n{mcq['question']}\n{str(mcq['options'])}\n{mcq['correct_answer']}",
                    str(validation)
                )
            except Exception:
                invalid_indices.append(i)

        return {
            "valid_mcqs": [mcq for i, mcq in enumerate(mcqs) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(self.get_total_token_usage())
        }

    def validate_flashcards(self, flashcards: List[Dict], context, areas: List[str]) -> Dict[str, Any]:
        invalid_indices = []
        for i, card in enumerate(flashcards):
            if not all(key in card for key in ["front", "back", "topic"]):
                invalid_indices.append(i)
                continue

            if any(card["front"] == other["front"] for other in flashcards[:i]):
                invalid_indices.append(i)
                continue

            prompt = PromptTemplate.from_template("""
                Validate if this flashcard is valid based on the following criteria:
                1. Content is relevant to the context
                2. Topic matches one of the focus areas
                3. Front and back are clear and accurate

                Context: {context}
                Focus Areas: {areas}
                Front: {front}
                Back: {back}
                Topic: {topic}

                Return JSON: {{"is_valid": boolean, "reason": "explanation if invalid"}}
            """)

            try:
                response = self._run_chain(prompt, {
                    "context": context,
                    "areas": areas,
                    "front": card["front"],
                    "back": card["back"],
                    "topic": card["topic"],
                })
                validation = json.loads(str(response))
                if not validation.get("is_valid", False):
                    invalid_indices.append(i)
                self.record_token_usage(
                    f"{_format_docs(context)}\n{card['front']}\n{card['back']}\n{card['topic']}",
                    str(validation)
                )
            except Exception:
                invalid_indices.append(i)

        return {
            "valid_flashcards": [card for i, card in enumerate(flashcards) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(self.get_total_token_usage())
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
            return {
                "is_valid": validation.get("is_valid", False),
                "reason": validation.get("reason", ""),
                "needs_regeneration": not validation.get("is_valid", False),
                "token_usage": str(self.get_total_token_usage())
            }
        except Exception:
            return {
                "is_valid": False,
                "reason": "Failed to validate notes",
                "needs_regeneration": True,
                "token_usage": str(self.get_total_token_usage())
            }
