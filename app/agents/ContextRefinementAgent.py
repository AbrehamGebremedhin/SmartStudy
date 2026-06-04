import os
import json
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.documents import Document
from langchain_deepseek import ChatDeepSeek
from langchain_core.prompts import PromptTemplate
from RetrievalAgent import RetrievalAgent
import tiktoken

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def _format_docs(context) -> str:
    if isinstance(context, list):
        return "\n\n".join(
            doc.page_content if isinstance(doc, Document) else str(doc)
            for doc in context
        )
    return str(context)


@dataclass
class RefinementResponse:
    context: object  # List[Document] or str
    parsed_answer: Dict[str, Any]
    summary: Dict[str, Any]
    error: Optional[str] = None
    token_usage: Optional[str] = None


@dataclass
class TokenCount:
    input_tokens: int
    output_tokens: int
    total_cost: float

    def __str__(self):
        return f"Input tokens: {self.input_tokens}\nOutput tokens: {self.output_tokens}\nTotal tokens: {self.input_tokens + self.output_tokens}\nEstimated cost: ${self.total_cost:.4f}"


class ContextRefinementError(Exception):
    pass


class ContextRefinementAgent:
    def __init__(self):
        load_dotenv("./.env")
        self.logger = logging.getLogger(__name__)

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ContextRefinementError("DEEPSEEK_API_KEY not found in environment")

        try:
            self.llm = ChatDeepSeek(model="deepseek-v4-flash", api_key=api_key)
            self.retrieval_agent = RetrievalAgent()
            self.parser = JsonOutputParser()
            self._prompt_cache: Dict[str, PromptTemplate] = {}
            # NOTE: tiktoken's gpt-3.5-turbo encoding is an APPROXIMATION for DeepSeek, which
            # uses a different tokenizer. Token counts and cost estimates are indicative only.
            self.token_counter = tiktoken.encoding_for_model("gpt-3.5-turbo")
            self.COST_PER_1M_INPUT = 0.14   # DeepSeek-V4-Flash
            self.COST_PER_1M_OUTPUT = 0.28  # DeepSeek-V4-Flash
        except Exception as e:
            raise ContextRefinementError(f"Failed to initialize services: {str(e)}")

    def validate_inputs(self, subject: str, question: str, grade: Optional[int] = None, unit: Optional[str] = None) -> None:
        if not all([subject, question]):
            raise ValueError("Subject and question must not be empty")
        if grade is not None and (not isinstance(grade, int) or grade < 1 or grade > 12):
            raise ValueError("Grade must be an integer between 1 and 12")
        if not isinstance(subject, str) or not isinstance(question, str):
            raise ValueError("Subject and question must be strings")

    def _run_chain(self, prompt: PromptTemplate, inputs: dict) -> str:
        if "context" in inputs:
            inputs = {**inputs, "context": _format_docs(inputs["context"])}
        chain = prompt | self.llm | StrOutputParser()
        return chain.invoke(inputs)

    def get_prompt(self, type_request: str) -> PromptTemplate:
        if type_request in self._prompt_cache:
            return self._prompt_cache[type_request]
        if type_request == "chat":
            prompt_template = """
                <|system|> You are an expert in extracting key points from educational content to assist in learning. Your task is to analyze the provided context and the student's question in the subject of {subject}, and then identify key points that address the student's query and provide additional helpful information.

                IMPORTANT: Your response must be formatted as a single-line JSON string with no line breaks or escaped characters, like this: {{"keypoints":["Point 1", "Point 2"]}}

                Context:
                {context}

                Student Question:
                {student_question}

                Subject: {subject}

                Instructions:
                1. Identify key points that answer the student's question directly.
                2. Include relevant additional information from the context that enhances understanding.
                3. Do not add any information not explicitly found in the context.
                4. Avoid repeating similar points; ensure clarity and uniqueness.
                5. Format your response as a single-line JSON string.

                Rules for JSON Formatting:
                - Use double quotes for all keys and values.
                - Return ONLY the JSON string with no extra text or line breaks.
                - Ensure the JSON is properly escaped and valid.
            """
        elif type_request == "notes":
            prompt_template = """
                <|system|> You are an expert in organizing and structuring educational content for detailed note generation. Analyze the given context in the subject of {subject} to identify key topics, concepts, and relationships that should be included in comprehensive study notes.

                IMPORTANT: Your response must be formatted as a single-line JSON string with no line breaks or escaped characters, like this: {{"sections": ["Section 1", "Section 2"], "key_concepts": ["Concept 1", "Concept 2"], "relationships": ["Relationship 1", "Relationship 2"], "learning_objectives": ["Objective 1", "Objective 2"]}}

                Context:
                {context}

                Student Question: {student_question}
                Subject: {subject}

                Instructions:
                1. Identify main sections for structured notes
                2. Extract key concepts that need detailed explanation
                3. Identify relationships between concepts
                4. Define clear learning objectives
                5. Format your response as a single-line JSON string

                Rules for JSON Formatting:
                - Use double quotes for all keys and values
                - Return ONLY the JSON string with no extra text or line breaks
                - Ensure the JSON is properly escaped and valid
            """
        else:
            prompt_template = """
                <|system|> You are an expert in identifying areas within educational content suitable for generating MCQs and flashcards. Analyze the given context in the subject of {subject} to determine areas from which questions or flashcards should be created.

                IMPORTANT: Your response must be formatted as a single-line JSON string with no line breaks or escaped characters, like this: {{"areas":["Area", "Area"]}}

                Context:
                {context}

                Subject: {subject}

                Instructions:
                1. Identify specific areas or topics within the context that are suitable for MCQs or flashcards.
                2. Avoid general topics like "unit summary" or "chapter overview."
                3. Focus on areas with clearly defined concepts, facts, or processes that lend themselves to concise questions or answers.
                4. Ensure areas are distinct and non-overlapping to avoid redundancy.
                5. Format your response as a single-line JSON string.

                Rules for JSON Formatting:
                - Use double quotes for all keys and values.
                - Return ONLY the JSON string with no extra text or line breaks.
                - Ensure the JSON is properly escaped and valid.
            """

        template = PromptTemplate.from_template(prompt_template)
        self._prompt_cache[type_request] = template
        return template

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def summarize_content(self, context, max_length: int = 500, include_structure: bool = False) -> Dict[str, Any]:
        base_prompt = """
            You are an expert educational content summarizer. Analyze the provided context and create a structured summary.

            IMPORTANT: Your response must be formatted as a single-line JSON string with no line breaks or escaped characters, like this:
            {{"brief_summary": "Short 1-2 sentence overview",
              "key_points": ["Point 1", "Point 2", "Point 3"],
              "main_ideas": ["Main idea 1", "Main idea 2"],
              "detailed_summary": "Longer detailed summary"}}

            Context: {context}

            Instructions:
            1. Create a brief summary (max 2 sentences)
            2. Extract 3-5 key points that capture essential information
            3. Identify 2-3 main ideas or concepts
            4. Provide a detailed summary (max {max_length} characters)
            5. Ensure all content is directly derived from the context
            6. Use clear, concise language suitable for educational purposes

            Rules for JSON Formatting:
            - Use double quotes for all keys and values
            - Return ONLY the JSON string with no extra text
            - Ensure the JSON is properly escaped and valid
        """

        if include_structure:
            base_prompt += """
                Additional Structure Elements:
                - Identify hierarchical relationships between concepts
                - Suggest learning sequence
                - Note prerequisites if any
                - Highlight practical applications
            """

        prompt = PromptTemplate.from_template(base_prompt)

        try:
            answer = self._run_chain(prompt, {"context": context, "max_length": max_length})
            clean_answer = str(answer.strip()).replace("\\", '')
            parsed_answer = self.parser.parse(clean_answer)

            required_fields = ['brief_summary', 'key_points', 'main_ideas', 'detailed_summary']
            if not all(field in parsed_answer for field in required_fields):
                raise ValueError("Missing required fields in summary response")

            return parsed_answer

        except ValueError as e:
            return {"error": f"Summary structure error: {str(e)}"}
        except Exception as e:
            return {"error": f"Summarization error: {str(e)}"}

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

    def query_db(self, subject: str, question: str, grade: Optional[int] = None, unit: Optional[str] = None, type_req: str = "chat") -> RefinementResponse:
        try:
            self.validate_inputs(subject, question, grade, unit)
            self.logger.info(f"Processing query - Subject: {subject}, Question: {question}")

            if type_req == "notes":
                context = self.retrieval_agent.query_vector_store(
                    subject, question, grade, unit, "notes", k_multiplier=1.25
                )
            elif type_req == "chat":
                # Pass grade through so chat retrieval is scoped to the student's grade when known
                context = self.retrieval_agent.query_vector_store(subject, question, grade, None, type_req)
            else:
                context = self.retrieval_agent.query_vector_store(subject, question, grade, unit, type_req)

            if not context:
                return RefinementResponse(
                    context="",
                    parsed_answer={},
                    summary={},
                    error="No relevant documents found"
                )

            prompt = self.get_prompt(type_req)
            answer = self._run_chain(prompt, {
                "context": context,
                "student_question": question,
                "subject": subject,
            })

            if type_req == "notes":
                summary = self.summarize_content(context, max_length=1000, include_structure=True)
            else:
                summary = self.summarize_content(context)

            clean_answer = str(answer.strip()).replace("\\", '')
            parsed_answer = self.parser.parse(clean_answer)

            token_usage = self.record_token_usage(
                f"{_format_docs(context)}\n{question}\n{subject}",
                str(parsed_answer)
            )

            self.logger.info("Successfully processed query")
            return RefinementResponse(
                context=context,
                parsed_answer=parsed_answer,
                summary=summary,
                error=None,
                token_usage=str(token_usage)
            )

        except ValueError as e:
            self.logger.error(f"Validation error: {str(e)}")
            return RefinementResponse(context="", parsed_answer={}, summary={}, error=f"Validation error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error processing query: {str(e)}")
            return RefinementResponse(context="", parsed_answer={}, summary={}, error=f"Processing error: {str(e)}")
