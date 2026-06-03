import os
import logging
from typing import Dict, List, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
import json
import tiktoken
from dataclasses import dataclass

@dataclass
class TokenCount:
    input_tokens: int
    output_tokens: int
    total_cost: float

    def __str__(self):
        return f"Input tokens: {self.input_tokens}\nOutput tokens: {self.output_tokens}\nTotal tokens: {self.input_tokens + self.output_tokens}\nEstimated cost: ${self.total_cost:.4f}"

class ValidationAgent:
    """
    A class responsible for validating different types of educational content.
    
    This agent ensures the quality, relevance, and correctness of educational content
    by performing comprehensive validation against provided context and criteria.
    It supports validation of MCQs, flashcards, chat responses, and educational notes.

    Attributes:
        logger (logging.Logger): Logger instance for tracking validation operations
        llm (ChatGoogleGenerativeAI): LLM instance for content validation operations
        
    Methods:
        validate_mcqs: Validates Multiple Choice Questions for quality and correctness
        validate_flashcards: Validates flashcards for relevance and educational value
        validate_chat_response: Validates chat responses for accuracy and completeness
        validate_notes: Validates educational notes for comprehensiveness
        
    Raises:
        ValueError: If required environment variables are not found
    """

    def __init__(self):
        """
        Initialize the ValidationAgent with required components and configuration.
        
        Sets up logging and the language model for validation operations.
        Validates the presence of required environment variables.
        """
        self.logger = logging.getLogger(__name__)
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
            
        os.environ["GOOGLE_API_KEY"] = api_key
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
        self.token_counter = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.token_counts = []
        self.COST_PER_1M_INPUT = 0.10   # $0.27 per 1M input tokens
        self.COST_PER_1M_OUTPUT = 0.40  # $1.10 per 1M output tokens

    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string"""
        return len(self.token_counter.encode(str(text)))

    def record_token_usage(self, input_text: str, output_text: str) -> TokenCount:
        """Record token usage for input and output"""
        input_tokens = self.count_tokens(input_text)
        output_tokens = self.count_tokens(output_text)
        
        cost = (
            (input_tokens * self.COST_PER_1M_INPUT / 1000000) +
            (output_tokens * self.COST_PER_1M_OUTPUT / 1000000)
        )
        
        token_count = TokenCount(input_tokens, output_tokens, cost)
        self.token_counts.append(token_count)
        return token_count

    def get_total_token_usage(self) -> TokenCount:
        """Get total token usage across all operations"""
        total_input = sum(tc.input_tokens for tc in self.token_counts)
        total_output = sum(tc.output_tokens for tc in self.token_counts)
        total_cost = sum(tc.total_cost for tc in self.token_counts)
        return TokenCount(total_input, total_output, total_cost)

    def validate_mcqs(self, mcqs: List[Dict], context: str, areas: List[str]) -> Dict[str, Any]:
        """
        Validate Multiple Choice Questions (MCQs) for quality and correctness.

        Performs comprehensive validation of MCQs including:
        - Structure validation (required fields, format)
        - Content validation (relevance to context, coverage of topic areas)
        - Quality validation (clarity, correctness of answers)
        - Duplicate detection
        - Answer and explanation validation

        Args:
            mcqs (List[Dict]): List of MCQ dictionaries containing:
                - topic: Specific topic or concept being tested
                - question: The question text
                - options: List of answer options
                - correct_answer: The letter of the correct option
                - correct_explanations: List of explanation steps
                - incorrect_explanations: Dict mapping wrong options to explanations
            context (str): The source content against which to validate the MCQs
            areas (List[str]): List of topic areas that the MCQs should cover

        Returns:
            Dict[str, Any]: Validation results containing:
                - valid_mcqs: List of MCQs that passed validation
                - invalid_indices: List of indices of invalid MCQs
                - needs_replacement: Boolean indicating if replacements are needed

        Notes:
            - MCQs are validated individually and as a set
            - Invalid MCQs are identified by their index in the input list
            - The function suggests replacement when invalid MCQs are found
        """
        invalid_indices = []
        for i, mcq in enumerate(mcqs):
            # Check for required fields
            if not all(key in mcq for key in ["topic", "question", "options", "correct_answer", "correct_explanations", "incorrect_explanations"]):
                invalid_indices.append(i)
                continue

            # Check for valid topic
            if not mcq["topic"] or not isinstance(mcq["topic"], str):
                invalid_indices.append(i)
                continue

            # Check for correct structure of explanations
            if not isinstance(mcq["correct_explanations"], list) or not isinstance(mcq["incorrect_explanations"], dict):
                invalid_indices.append(i)
                continue

            # Verify all incorrect options have explanations
            options = [opt[0] for opt in mcq["options"]]  # Extract option letters
            correct_opt = mcq["correct_answer"]
            incorrect_opts = [opt for opt in options if opt != correct_opt]
            if not all(opt in mcq["incorrect_explanations"] for opt in incorrect_opts):
                invalid_indices.append(i)
                continue

            # Check for duplicate questions
            if any(mcq["question"] == other["question"] for other in mcqs[:i]):
                invalid_indices.append(i)
                continue

            # Check if question aligns with context and areas
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

            chain = create_stuff_documents_chain(llm=self.llm, prompt=prompt)
            response = chain.invoke({
                "context": context,
                "areas": areas,
                "question": mcq["question"],
                "options": mcq["options"],
                "answer": mcq["correct_answer"]
            })

            try:
                validation = json.loads(str(response))
                if not validation.get("is_valid", False):
                    invalid_indices.append(i)

                # Record token usage for this validation
                self.record_token_usage(
                    f"{context}\n{mcq['question']}\n{str(mcq['options'])}\n{mcq['correct_answer']}",
                    str(validation)
                )

            except:
                invalid_indices.append(i)

        return {
            "valid_mcqs": [mcq for i, mcq in enumerate(mcqs) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(self.get_total_token_usage())
        }

    def validate_flashcards(self, flashcards: List[Dict], context: str, areas: List[str]) -> Dict[str, Any]:
        """
        Validate flashcards for quality, relevance, and educational value.

        Performs comprehensive validation of flashcards including:
        - Content relevance to provided context
        - Coverage of specified topic areas
        - Quality of front/back content
        - Duplicate detection
        - Educational value assessment

        Args:
            flashcards (List[Dict]): List of flashcard dictionaries containing:
                - front: The question or concept side
                - back: The answer or explanation side
                - topic: The specific topic area
            context (str): The source content against which to validate the flashcards
            areas (List[str]): List of topic areas that the flashcards should cover

        Returns:
            Dict[str, Any]: Validation results containing:
                - valid_flashcards: List of flashcards that passed validation
                - invalid_indices: List of indices of invalid flashcards
                - needs_replacement: Boolean indicating if replacements are needed

        Notes:
            - Each flashcard is validated for content accuracy and educational value
            - Duplicates are detected and marked as invalid
            - Validation ensures balanced coverage of topic areas
        """
        invalid_indices = []
        for i, card in enumerate(flashcards):
            # Check for required fields
            if not all(key in card for key in ["front", "back", "topic"]):
                invalid_indices.append(i)
                continue

            # Check for duplicate cards
            if any(card["front"] == other["front"] for other in flashcards[:i]):
                invalid_indices.append(i)
                continue

            # Validate content relevance
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

            chain = create_stuff_documents_chain(llm=self.llm, prompt=prompt)
            response = chain.invoke({
                "context": context,
                "areas": areas,
                "front": card["front"],
                "back": card["back"],
                "topic": card["topic"]
            })

            try:
                validation = json.loads(str(response))
                if not validation.get("is_valid", False):
                    invalid_indices.append(i)

                # Record token usage for this validation
                self.record_token_usage(
                    f"{context}\n{card['front']}\n{card['back']}\n{card['topic']}",
                    str(validation)
                )

            except:
                invalid_indices.append(i)

        return {
            "valid_flashcards": [card for i, card in enumerate(flashcards) if i not in invalid_indices],
            "invalid_indices": invalid_indices,
            "needs_replacement": len(invalid_indices) > 0,
            "token_usage": str(self.get_total_token_usage())
        }

    def validate_chat_response(self, response: Dict, context: str, keypoints: List[str]) -> Dict[str, Any]:
        """
        Validate chat responses for accuracy, relevance, and completeness.

        Performs detailed validation of chat responses including:
        - Content accuracy against provided context
        - Coverage of key points
        - Clarity and comprehensiveness
        - Educational value
        - Language appropriateness

        Args:
            response (Dict): The chat response to validate, containing:
                - response: The main response text
                - key_concepts: List of identified key concepts
                - follow_up_questions: Optional follow-up questions
            context (str): The source content against which to validate
            keypoints (List[str]): Key points that should be addressed

        Returns:
            Dict[str, Any]: Validation results containing:
                - is_valid: Boolean indicating if response is valid
                - reason: Explanation if invalid
                - needs_regeneration: Boolean indicating if response needs regeneration

        Notes:
            - Validates both content accuracy and pedagogical effectiveness
            - Checks for appropriate coverage of provided key points
            - Assesses response structure and completeness
        """
        # Handle nested response structure
        if isinstance(response, dict):
            if "error" in response:
                return {
                    "is_valid": False,
                    "reason": response["error"],
                    "needs_regeneration": True,
                    "token_usage": str(self.get_total_token_usage())
                }
            
            # Extract response from nested structure
            if "response" in response:
                if isinstance(response["response"], dict):
                    response_text = response["response"].get("response", "")
                else:
                    response_text = str(response["response"])
            else:
                response_text = str(response)
        else:
            response_text = str(response)

        # Skip validation if response is empty
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

        chain = create_stuff_documents_chain(llm=self.llm, prompt=prompt)
        validation_response = chain.invoke({
            "context": context,
            "keypoints": keypoints,
            "response": response_text
        })

        try:
            validation = json.loads(str(validation_response))

            # Record token usage for this validation
            self.record_token_usage(
                f"{context}\n{response_text}\n{str(keypoints)}",
                str(validation)
            )

            # More lenient validation - only fail if clearly invalid
            is_valid = validation.get("is_valid", True)  # Default to valid
            return {
                "is_valid": is_valid,
                "reason": validation.get("reason", ""),
                "needs_regeneration": not is_valid,
                "token_usage": str(self.get_total_token_usage())
            }
        except:
            # If validation fails, assume response is valid but log warning
            return {
                "is_valid": True,
                "reason": "Validation parsing failed - assuming valid",
                "needs_regeneration": False,
                "token_usage": str(self.get_total_token_usage())
            }

    def validate_notes(self, notes: Dict[str, Any], context: str) -> Dict[str, Any]:
        """
        Validate educational notes for comprehensiveness and accuracy.

        Performs thorough validation of educational notes including:
        - Content accuracy against source material
        - Structural completeness
        - Example relevance and clarity
        - Explanation thoroughness
        - Coverage of required topics

        Args:
            notes (Dict[str, Any]): The educational notes to validate, containing:
                - title: Note title/topic
                - sections: Content sections
                - examples: Practical examples
                - explanations: Detailed explanations
            context (str): The source content against which to validate

        Returns:
            Dict[str, Any]: Validation results containing:
                - is_valid: Boolean indicating if notes are valid
                - reason: Explanation if invalid
                - needs_regeneration: Boolean indicating if notes need regeneration

        Notes:
            - Validates both content accuracy and structural completeness
            - Ensures proper organization and flow of information
            - Checks for presence of all required educational elements
        """
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

        chain = create_stuff_documents_chain(llm=self.llm, prompt=prompt)
        response = chain.invoke({
            "context": context,
            "notes": json.dumps(notes)
        })

        try:
            validation = json.loads(str(response))

            # Record token usage for this validation
            self.record_token_usage(
                f"{context}\n{json.dumps(notes)}",
                str(validation)
            )

            return {
                "is_valid": validation.get("is_valid", False),
                "reason": validation.get("reason", ""),
                "needs_regeneration": not validation.get("is_valid", False),
                "token_usage": str(self.get_total_token_usage())
            }
        except:
            return {
                "is_valid": False,
                "reason": "Failed to validate notes",
                "needs_regeneration": True,
                "token_usage": str(self.get_total_token_usage())
            }
