import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from functools import lru_cache
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from RetrievalAgent import RetrievalAgent  # Fixed the class name here
import tiktoken
from dataclasses import dataclass

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

@dataclass
class RefinementResponse:
    """
    Structured response class for context refinement results.
    
    Attributes:
        context (str): The refined context text
        parsed_answer (Dict[str, Any]): Structured parsing of the context
        summary (Dict[str, Any]): Summary of key points
        error (Optional[str]): Error message if processing failed
        token_usage (Optional[str]): Token usage information
    """
    context: str
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
    """Custom exception for ContextRefinementAgent errors."""
    pass

class ContextRefinementAgent:
    """
    A class responsible for refining and structuring educational context.
    
    This agent processes raw educational content into structured formats,
    extracts key information, and provides summaries suitable for different
    educational content types.

    Attributes:
        logger: Logging instance for tracking operations
        llm: Instance of ChatGoogleGenerativeAI
        retrieval_agent: Instance of RetrievalAgent
        parser: JSON output parser for structured responses
    """

    def __init__(self):
        """Initialize the ContextRefinementAgent with configuration and logging"""
        load_dotenv("./config.env")
        self.logger = logging.getLogger(__name__)
        
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ContextRefinementError("GOOGLE_API_KEY not found in environment")
        
        os.environ["GOOGLE_API_KEY"] = api_key
        
        try:
            self.llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
            self.retrieval_agent = RetrievalAgent()  # Fixed the class name here
            self.parser = JsonOutputParser()
            self.token_counter = tiktoken.encoding_for_model("gpt-3.5-turbo")
            self.token_counts = []
            self.COST_PER_1M_INPUT = 0.27   # $0.27 per 1M input tokens
            self.COST_PER_1M_OUTPUT = 1.10  # $1.10 per 1M output tokens
        except Exception as e:
            raise ContextRefinementError(f"Failed to initialize services: {str(e)}")

    def validate_inputs(self, subject: str, question: str, grade: Optional[int] = None, unit: Optional[str] = None) -> None:
        """
        Validate input parameters for content refinement.

        Args:
            subject (str): Subject area
            question (str): Query or prompt
            grade (Optional[int]): Grade level
            unit (Optional[str]): Unit identifier

        Raises:
            ValueError: If inputs fail validation
        """
        if not all([subject, question]):
            raise ValueError("Subject and question must not be empty")
        if grade is not None and (not isinstance(grade, int) or grade < 1 or grade > 12):
            raise ValueError("Grade must be an integer between 1 and 12")
        if not isinstance(subject, str) or not isinstance(question, str):
            raise ValueError("Subject and question must be strings")

    @lru_cache(maxsize=128)
    def get_prompt(self, type_request: str) -> PromptTemplate:
        """
        Get cached prompt template based on request type.

        Retrieves and returns a specific prompt template optimized for different
        types of educational content generation. Uses caching to improve performance.

        Args:
            type_request (str): Type of content being generated. Can be:
                - "chat": For interactive Q&A responses
                - "notes": For comprehensive study notes
                - "quiz": For MCQs and flashcards (default template)

        Returns:
            PromptTemplate: Template customized for the specified request type

        Notes:
            - Implements LRU caching for performance optimization
            - Different templates for different content types
            - Includes specific instructions per content type
            - Enforces consistent JSON response format
            - Optimized for educational content generation

        Cache Info:
            - Uses @lru_cache with maxsize=128
            - Caches based on type_request parameter
            - Improves response time for repeated requests
        """
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
                1. Identify key points that answer the student’s question directly.
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
        
        return PromptTemplate.from_template(prompt_template)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def summarize_content(self, context: str, max_length: int = 500, include_structure: bool = False) -> Dict[str, Any]:
        """
        Create structured summary of educational content.

        Args:
            context (str): Content to summarize
            max_length (int): Maximum length of detailed summary
            include_structure (bool): Include structural elements

        Returns:
            Dict[str, Any]: Structured summary with key points
        """
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
        chain = create_stuff_documents_chain(llm=self.llm, prompt=prompt)

        try:
            answer = chain.invoke({
                "context": context,
                "max_length": max_length
            })

            clean_answer = str(answer.strip()).replace("\\", '')
            parsed_answer = self.parser.parse(clean_answer)

            # Validate required fields
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
        total_input = sum(tc.input_tokens for tc in self.token_counts)
        total_output = sum(tc.output_tokens for tc in self.token_counts)
        total_cost = sum(tc.total_cost for tc in self.token_counts)
        return TokenCount(total_input, total_output, total_cost)

    def query_db(self, subject: str, question: str, grade: Optional[int] = None, unit: Optional[str] = None, type_req: str = "chat") -> RefinementResponse:
        """
        Query database and refine context for educational content generation.

        Args:
            subject (str): Subject area
            question (str): Query or prompt
            grade (Optional[int]): Grade level
            unit (Optional[str]): Unit identifier
            type_req (str): Type of content being generated

        Returns:
            RefinementResponse: Structured response with refined context
        """
        try:
            # Validate inputs
            self.validate_inputs(subject, question, grade, unit)
            
            # Log query attempt
            self.logger.info(f"Processing query - Subject: {subject}, Question: {question}")

            # Modify context retrieval for notes
            if type_req == "notes":
                # Get broader context for comprehensive notes
                context = self.retrieval_agent.query_vector_store(
                    subject, 
                    question, 
                    grade, 
                    unit,
                    "notes",
                    k_multiplier=1.25  # Adjusted to a more conservative value
                )
            else:
                # Get context without grade and unit for chat queries
                if type_req == "chat":
                    context = self.retrieval_agent.query_vector_store(subject, question, None, None, type_req)
                else:
                    context = self.retrieval_agent.query_vector_store(subject, question, grade, unit, type_req)
                
            if not context:
                return RefinementResponse(
                    context="",
                    parsed_answer={},
                    summary={},
                    error="No relevant documents found"
                )

            # Get and execute chain
            prompt = self.get_prompt(type_req)
            chain = create_stuff_documents_chain(llm=self.llm, prompt=prompt)
            
            answer = chain.invoke({
                "context": context,
                "student_question": question,
                "subject": subject,
            })

            # Enhanced summary for notes
            if type_req == "notes":
                summary = self.summarize_content(
                    context,
                    max_length=1000,  # Longer summary for notes
                    include_structure=True  # Add structural elements
                )
            else:
                summary = self.summarize_content(context)

            # Parse response
            clean_answer = str(answer.strip()).replace("\\", '')
            parsed_answer = self.parser.parse(clean_answer)

            # Record token usage
            token_usage = self.record_token_usage(
                f"{context}\n{question}\n{subject}",
                str(parsed_answer)
            )

            self.logger.info("Successfully processed query")
            return RefinementResponse(
                context=context,
                parsed_answer=parsed_answer,
                summary=summary,
                error=None,
                token_usage=str(token_usage)  # Add token usage to response
            )

        except ValueError as e:
            self.logger.error(f"Validation error: {str(e)}")
            return RefinementResponse(
                context="",
                parsed_answer={},
                summary={},
                error=f"Validation error: {str(e)}"
            )
        except Exception as e:
            self.logger.error(f"Error processing query: {str(e)}")
            return RefinementResponse(
                context="",
                parsed_answer={},
                summary={},
                error=f"Processing error: {str(e)}"
            )
