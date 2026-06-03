import os
import functools
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document
from RetrievalAgent import RetrievalAgent
import json
import logging
from ContextRefinementAgent import ContextRefinementAgent
from ValidationAgent import ValidationAgent
from datetime import datetime
import uuid
from dataclasses import dataclass, field
import tiktoken


def _format_docs(context) -> str:
    if isinstance(context, list):
        return "\n\n".join(
            doc.page_content if isinstance(doc, Document) else str(doc)
            for doc in context
        )
    return str(context)

@dataclass
class ChatMessage:
    """Represents a single message in a chat session"""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class ChatSession:
    """Represents a chat session with history"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    messages: List[ChatMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    subject: str = ""
    
    def add_message(self, role: str, content: str):
        """Add a new message to the chat history"""
        self.messages.append(ChatMessage(role=role, content=content))
    
    def get_recent_context(self, max_messages: int = 5) -> str:
        """Get the most recent conversation context"""
        recent = self.messages[-max_messages:] if self.messages else []
        return "\n".join([f"{msg.role}: {msg.content}" for msg in recent])

load_dotenv("./.env")

def retry_on_none(max_retries=3):
    """
    Decorator that retries a function if it returns None.

    Provides automatic retry functionality for functions that might fail temporarily.
    Useful for handling transient failures in API calls or resource access.

    Args:
        max_retries (int): Maximum number of retry attempts before failing

    Returns:
        Callable: Decorated function that implements retry logic

    Raises:
        ValueError: If no valid response is received after max retries
        
    Notes:
        - Retries immediately without delay
        - Stops retrying if function returns non-None value
        - Useful for functions with potential transient failures
    """
    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                result = func(*args, **kwargs)
                if result is not None:
                    return result
            raise ValueError(f"Failed to get a valid response after {max_retries} attempts")
        return wrapper
    return decorator_retry

@dataclass
class TokenCount:
    input_tokens: int
    output_tokens: int
    total_cost: float

    def __str__(self):
        return f"Input tokens: {self.input_tokens}\nOutput tokens: {self.output_tokens}\nTotal tokens: {self.input_tokens + self.output_tokens}\nEstimated cost: ${self.total_cost:.4f}"

class GenerationAgent:
    """
    A class responsible for generating various types of educational content.
    
    This agent handles the generation of MCQs, flashcards, chat responses, and detailed 
    study notes using LLM. It includes validation, context refinement, and error handling.

    Attributes:
        logger: Logging instance for tracking operations
        llm: Instance of ChatGoogleGenerativeAI for content generation
        context_agent: Instance of ContextRefinementAgent
        validation_agent: Instance of ValidationAgent
        stem_subjects: List of STEM subject identifiers
        humanities_subjects: List of humanities subject identifiers
    """

    def __init__(self):
        """Initialize the GenerationAgent with required components"""
        load_dotenv("./.env")
        self.logger = logging.getLogger(__name__)

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment")

        self.llm = ChatDeepSeek(model="deepseek-chat", api_key=api_key)
        self.context_agent = ContextRefinementAgent()
        self.validation_agent = ValidationAgent()
        self.stem_subjects = ["maths", "physics", "chemistry", "biology", "economics"]
        self.humanities_subjects = ["english", "history", "geography", "civics", "general_business"]
        self.active_sessions: Dict[str, ChatSession] = {}
        self.token_counter = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.token_counts = []
        self.COST_PER_1M_INPUT = 0.27   # DeepSeek-V3: $0.27 per 1M input tokens
        self.COST_PER_1M_OUTPUT = 1.10  # DeepSeek-V3: $1.10 per 1M output tokens

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

    def create_chat_session(self, subject: str, initial_title: str = "New Chat") -> str:
        """Create a new chat session and return its ID"""
        session = ChatSession(subject=subject, title=initial_title)
        self.active_sessions[session.id] = session
        return session.id
        
    def get_chat_session(self, session_id: str) -> Optional[ChatSession]:
        """Retrieve a chat session by ID"""
        return self.active_sessions.get(session_id)
        
    def update_session_title(self, session_id: str, new_title: str) -> bool:
        """Update the title of a chat session"""
        if session := self.active_sessions.get(session_id):
            session.title = new_title
            return True
        return False

    def _get_subject_rules(self, subject: str) -> str:
        """
        Get subject-specific rules for content generation.

        Args:
            subject (str): The subject identifier

        Returns:
            str: Specific rules and guidelines for the given subject
        """
        if subject.lower() in self.stem_subjects:
            return """
                - The questions with workout questions should contain workout steps
                - Use ^ in place of superscript and _ in place of subscript
                - Include step-by-step solutions where applicable
            """
        elif subject.lower() in self.humanities_subjects:
            return """
                - No essay or paragraph-based questions
                - Focus on clear, concise factual questions
                - Include relevant historical/contextual references
            """
        elif subject.lower() == "sat":
            return """
                - Balance between maths and english questions (1:1 ratio)
                - Include step-by-step solutions for math problems
                - Follow SAT question format guidelines
            """
        return "- General format rules apply"  # Default rules

    def _clean_unicode(self, text: str) -> str:
        """
        Clean and normalize Unicode characters in text.

        Args:
            text (str): Text containing Unicode characters

        Returns:
            str: Cleaned text with standardized characters
        """
        if not isinstance(text, str):
            return text
            
        replacements = {
            # Superscript numbers
            '\u00b2': '^2',    # ²
            '\u00b3': '^3',    # ³
            '\u2070': '^0',    # ⁰
            '\u00b9': '^1',    # ¹
            '\u2074': '^4',    # ⁴
            '\u2075': '^5',    # ⁵
            '\u2076': '^6',    # ⁶
            '\u2077': '^7',    # ⁷
            '\u2078': '^8',    # ⁸
            '\u2079': '^9',    # ⁹
            # Superscript operators
            '\u207a': '^+',    # ⁺
            '\u207b': '^-',    # ⁻
            '\u207c': '^=',    # ⁼
            '\u207d': '^(',    # ⁽
            '\u207e': '^)',    # ⁾
            # Mathematical symbols
            '\u2013': '-',     # –
            '\u2014': '--',    # —
            '\u2212': '-',     # −
            '\u00d7': 'x',     # ×
            '\u00f7': '/',     # ÷
            '\u00b1': '+-',    # ±
            '\u221a': 'sqrt',  # √
            '\u221e': 'inf',   # ∞
            '\u2248': '~=',    # ≈
            '\u2260': '!=',    # ≠
            '\u2264': '<=',    # ≤
            '\u2265': '>=',    # ≥
            # Greek letters
            '\u03b1': 'alpha',  # α
            '\u03b2': 'beta',   # β
            '\u03b3': 'gamma',  # γ
            '\u03c0': 'pi',     # π
            '\u03bc': 'mu',     # μ
            # Quotes and formatting
            '\u2018': "'",     # '
            '\u2019': "'",     # '
            '\u201c': '"',     # "
            '\u201d': '"',     # "
            '\u2022': '*',     # •
            '\n': '\\n',       # newline
        }
        
        result = text
        for unicode_char, replacement in replacements.items():
            result = result.replace(unicode_char, replacement)
        return result

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """
        Parse and validate LLM response into structured format.

        Args:
            response (str): Raw LLM response string

        Returns:
            Dict[str, Any]: Parsed and validated response structure
        """
        try:
            # Clean and normalize the response string
            cleaned_response = response.strip()
            # Try to extract JSON if embedded in other text
            start_idx = cleaned_response.find('{')
            end_idx = cleaned_response.rfind('}') + 1
            if (start_idx != -1 and end_idx > start_idx):
                cleaned_response = cleaned_response[start_idx:end_idx]
                
            # Handle common JSON formatting issues
            cleaned_response = cleaned_response.replace('\n', ' ')
            cleaned_response = cleaned_response.replace('\\', '\\\\')
            
            # Parse the cleaned JSON
            parsed = json.loads(cleaned_response)
            
            # Clean Unicode in response text if present
            if isinstance(parsed, dict):
                if "response" in parsed:
                    if isinstance(parsed["response"], dict):
                        parsed["response"]["response"] = self._clean_unicode(parsed["response"]["response"])
                    else:
                        parsed["response"] = self._clean_unicode(str(parsed["response"]))
            
            # For chat responses, don't check for questions/flashcards structure
            if "response" in parsed or "key_concepts" in parsed:
                return parsed
                
            # For MCQs/flashcards, ensure expected structure
            if "questions" not in parsed and "flashcards" not in parsed:
                return {
                    "error": "Invalid response format",
                    "raw_response": cleaned_response
                }
            
            return parsed

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON response: {str(e)}")
            return {
                "error": f"Failed to parse response: {str(e)}",
                "raw_response": response
            }

    def _serialize_document(self, doc: Document) -> Dict[str, Any]:
        """
        Serialize a Document object into a dictionary format.

        Converts a Document instance into a dictionary representation suitable
        for JSON serialization or data transfer.

        Args:
            doc (Document): Document instance to serialize

        Returns:
            Dict[str, Any]: Dictionary containing:
                - page_content: The document's main content
                - metadata: Associated metadata dictionary
        """
        return {
            "page_content": doc.page_content,
            "metadata": doc.metadata
        }

    def _serialize_documents(self, docs: List[Document]) -> List[Dict[str, Any]]:
        """
        Serialize a list of Document objects into list of dictionaries.

        Maps a collection of Document instances to their dictionary representations
        for data transfer or storage.

        Args:
            docs (List[Document]): List of Document instances to serialize

        Returns:
            List[Dict[str, Any]]: List of serialized document dictionaries
        """
        return [self._serialize_document(doc) for doc in docs]

    @retry_on_none(max_retries=3)
    def generate_mcqs(self, subject: str, grade: int, unit: str, num_questions: int = 5, difficulty: str = "hard") -> Dict[str, Any]:
        """
        Generate multiple choice questions with comprehensive validation.

        Args:
            subject (str): Subject area
            grade (int): Grade level
            unit (str): Unit/chapter identifier
            num_questions (int): Number of questions to generate
            difficulty (str): Difficulty level - "easy", "medium", "hard", or "challenging"

        Returns:
            Dict[str, Any]: Generated MCQs with validation results
        """
        try:
            # Validate difficulty level
            if difficulty not in ["easy", "medium", "hard", "challenging"]:
                difficulty = "medium"  # Default to medium if invalid

            # Get refined context for MCQ generation
            context_response = self.context_agent.query_db(
                subject=subject,
                question=f"Generate {difficulty} MCQs for this content",
                grade=grade,
                unit=unit,
                type_req="quiz"
            )
            
            if context_response.error:
                return {"error": context_response.error}

            # Get subject-specific rules before creating the prompt
            subject_rules = self._get_subject_rules(subject)

            # Enhanced MCQ generation prompt with difficulty instructions
            prompt = PromptTemplate.from_template("""
                Generate {num_questions} {difficulty} multiple choice questions based on the following context.
                
                Subject Rules:
                {subject_rules}
                
                Difficulty Level: {difficulty}
                For {difficulty} questions:
                - Use complex, higher-order thinking that requires analysis and synthesis
                - Include questions that test deeper understanding rather than mere recall
                - Incorporate advanced concepts and applications
                - For STEM subjects, include multi-step problems requiring calculation or conceptual reasoning
                - For humanities, include questions requiring critical analysis and evaluation
                - Make distractors (wrong options) more sophisticated and plausible
                
                Return response as a JSON array with the following structure for each question:
                {{"questions": [
                    {{
                        "topic": "specific topic or concept being tested",
                        "question": "question text",
                        "options": ["A) option1", "B) option2", "C) option3", "D) option4"],
                        "correct_answer": "A",
                        "correct_explanations": [
                            "Step 1 of explanation",
                            "Step 2 of explanation",
                            "Final explanation"
                        ],
                        "incorrect_explanations": {{
                            "B": "Reason why B is wrong", "Additional detail",
                            "C": "Reason why C is wrong", "Additional detail",
                            "D": "Reason why D is wrong", "Additional detail"
                        }},
                        "workout_steps": "step by step solution (if applicable)",
                        "difficulty": "{difficulty}"
                    }}
                ]}}
                
                Context: {context}
                
                Areas to focus on: {areas}
                
                Ensure that:
                1. Each question has a clear specific topic
                2. Correct explanations are broken down into logical steps
                3. Each incorrect option has clear reasons why it's not correct
                4. All explanations are educational and help students understand the concept
                5. Questions match the {difficulty} difficulty level appropriately
            """)

            chain = prompt | self.llm | StrOutputParser()

            response = chain.invoke({
                "context": _format_docs(context_response.context),
                "areas": context_response.parsed_answer.get("areas", []),
                "num_questions": num_questions,
                "subject_rules": subject_rules,
                "difficulty": difficulty
            })
            
            parsed_response = self._parse_llm_response(str(response))

            # Validate MCQs
            validation_result = self.validation_agent.validate_mcqs(
                parsed_response.get("questions", []),
                context_response.context,
                context_response.parsed_answer.get("areas", [])
            )

            # Generate replacements if needed
            if validation_result["needs_replacement"]:
                replacement_count = len(validation_result["invalid_indices"])
                additional_response = chain.invoke({
                    "context": _format_docs(context_response.context),
                    "areas": context_response.parsed_answer.get("areas", []),
                    "num_questions": replacement_count,
                    "subject_rules": subject_rules,
                    "difficulty": difficulty
                })
                
                additional_parsed = self._parse_llm_response(str(additional_response))
                valid_questions = validation_result["valid_mcqs"] + additional_parsed.get("questions", [])

            else:
                valid_questions = validation_result["valid_mcqs"]

            self.record_token_usage(
                f"{_format_docs(context_response.context)}\n{subject_rules}\n{difficulty}",
                str(parsed_response)
            )

            return {
                "questions": valid_questions[:num_questions],
                "error": None,
                "difficulty": difficulty,
                "token_usage": str(self.get_total_token_usage())
            }

        except Exception as e:
            self.logger.error(f"Error generating MCQs: {str(e)}")
            return {
                "error": f"MCQ generation failed: {str(e)}",
                "difficulty": difficulty,
                "token_usage": str(self.get_total_token_usage())
            }

    def generate_flashcards(self, subject: str, num_cards: int = 5, topic: Optional[str] = None, 
                           grade: Optional[int] = None, unit: Optional[str] = None, 
                           difficulty: str = "medium") -> Dict[str, Any]:
        """
        Generate educational flashcards with validation.

        Args:
            subject (str): Subject area
            num_cards (int): Number of flashcards to generate
            topic (Optional[str]): Specific topic for flashcard generation
            grade (Optional[int]): Grade level
            unit (Optional[str]): Unit/chapter identifier
            difficulty (str): Difficulty level - "easy", "medium", "hard", or "challenging"

        Returns:
            Dict[str, Any]: Generated flashcards with validation results
        """
        try:
            # Validate difficulty level
            if difficulty not in ["easy", "medium", "hard", "challenging"]:
                difficulty = "medium"  # Default to medium if invalid
                
            # Determine the question based on the presence of topic
            if topic:
                question = f"Generate {difficulty} flashcards for this content on the topic of {topic}"
                context_response = self.context_agent.query_db(
                    subject=subject,
                    question=question,
                    grade=None,
                    unit=None,
                    type_req="chat"  # Use the same context fetching as chat response
                )
            else:
                question = f"Generate {difficulty} flashcards for this content"
                context_response = self.context_agent.query_db(
                    subject=subject,
                    question=question,
                    grade=grade,
                    unit=unit,
                    type_req="quiz"
                )
            
            if context_response.error:
                return {"error": context_response.error}

            # Check if context is empty
            if not context_response.context:
                return {"error": "No relevant documents found"}

            # Enhanced flashcard generation prompt with difficulty instructions
            prompt = PromptTemplate.from_template("""
                Generate {num_cards} {difficulty} flashcards based on the following context.
                
                Difficulty Level: {difficulty}
                For {difficulty} flashcards:
                - Focus on advanced concepts and deeper connections between ideas
                - Include more nuanced and complex information on the front and back
                - For STEM subjects, include formulas, derivations, or complex processes
                - For humanities, include analytical frameworks, critical perspectives, or theoretical applications
                - Make flashcards that test understanding rather than simple memorization
                - Create cards that require synthesis of multiple concepts
                
                Return response as a JSON array with the following structure:
                {{"flashcards": [
                    {{
                        "front": "concept or question",
                        "back": "explanation or answer",
                        "topic": "specific topic area",
                        "difficulty": "{difficulty}"
                    }}
                ]}}
                
                Context: {context}
                
                Areas to focus on: {areas}
                
                Ensure that:
                1. Each flashcard tests a substantial concept, not just terminology
                2. Explanations on the back are comprehensive but concise
                3. Cards include advanced applications or implications where appropriate
                4. Cards match the {difficulty} difficulty level appropriately
            """)

            chain = prompt | self.llm | StrOutputParser()

            response = chain.invoke({
                "context": _format_docs(context_response.context),
                "areas": context_response.parsed_answer.get("areas", []),
                "num_cards": num_cards,
                "difficulty": difficulty
            })
            
            parsed_response = self._parse_llm_response(str(response))

            # Validate flashcards
            validation_result = self.validation_agent.validate_flashcards(
                parsed_response.get("flashcards", []),
                context_response.context,
                context_response.parsed_answer.get("areas", [])
            )

            # Generate replacements if needed
            if validation_result["needs_replacement"]:
                replacement_count = len(validation_result["invalid_indices"])
                additional_response = chain.invoke({
                    "context": _format_docs(context_response.context),
                    "areas": context_response.parsed_answer.get("areas", []),
                    "num_cards": replacement_count,
                    "difficulty": difficulty
                })
                
                additional_parsed = self._parse_llm_response(str(additional_response))
                valid_cards = validation_result["valid_flashcards"] + additional_parsed.get("flashcards", [])

            else:
                valid_cards = validation_result["valid_flashcards"]

            # Get subject-specific rules before recording token usage
            subject_rules = self._get_subject_rules(subject)
            
            self.record_token_usage(
                f"{_format_docs(context_response.context)}\n{subject_rules}\n{difficulty}",
                str(parsed_response)
            )

            return {
                "flashcards": valid_cards[:num_cards],
                "error": None,
                "difficulty": difficulty,
                "token_usage": str(self.get_total_token_usage())
            }

        except Exception as e:
            self.logger.error(f"Error generating flashcards: {str(e)}")
            return {
                "error": f"Flashcard generation failed: {str(e)}",
                "difficulty": difficulty,
                "token_usage": str(self.get_total_token_usage())
            }

    def chat_response(self, subject: str, question: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate contextual educational responses to student questions with chat history support.
        """
        try:
            # Get or create chat session
            session = None
            if session_id:
                session = self.active_sessions.get(session_id)
            if not session:
                session_id = self.create_chat_session(subject)
                session = self.active_sessions[session_id]
                
            # Add user message to history
            session.add_message("user", question)
            
            # Get chat history context
            chat_history = session.get_recent_context()
            
            # Get refined context for chat response
            context_response = self.context_agent.query_db(
                subject=subject,
                question=question,
                grade=None,
                unit=None,
                type_req="chat"
            )
            
            if context_response.error:
                return {
                    "response": "",
                    "error": context_response.error,
                    "context": None,
                    "session_id": session_id,
                    "title": session.title
                }

            # Enhanced chat response prompt with title generation
            prompt = PromptTemplate.from_template("""
                You are an educational assistant helping a student understand a topic.
                Previous conversation:
                {chat_history}
                
                Using the context provided and the chat history, answer the student's question clearly and concisely.
                For new chat sessions, suggest a descriptive title that captures the main topic being discussed.
                For existing sessions, suggest a title update if the topic has shifted significantly.
                
                Context: {context}
                Question: {question}
                Key Points to Address: {keypoints}
                Current Title: {current_title}
                
                Respond with a simple JSON structure:
                {{
                    "title": "A clear, specific title describing the conversation topic",
                    "should_update_title": true/false,
                    "answer": "Your detailed, educational answer here",
                    "key_concepts": ["Key concept 1", "Key concept 2"],
                    "follow_up_questions": ["Related question 1?", "Related question 2?"]
                }}
            """)

            chain = prompt | self.llm | StrOutputParser()

            response = chain.invoke({
                "context": _format_docs(context_response.context),
                "question": question,
                "keypoints": context_response.parsed_answer.get("keypoints", []),
                "chat_history": chat_history,
                "current_title": session.title
            })

            # Parse the response with simpler structure
            parsed_response = self._parse_llm_response(str(response))
            
            # Update session title if needed
            if (session.title == "New Chat" or 
                parsed_response.get("should_update_title", False)) and "title" in parsed_response:
                new_title = parsed_response["title"]
                if new_title and new_title != session.title:
                    session.title = new_title

            # Add assistant response to history
            answer = parsed_response.get("answer", "No answer generated")
            session.add_message("assistant", answer)

            # Get subject-specific rules before recording token usage
            subject_rules = self._get_subject_rules(subject)
            
            self.record_token_usage(
                f"{_format_docs(context_response.context)}\n{subject_rules}",
                str(parsed_response)
            )

            return {
                "title": session.title,
                "content": {
                    "answer": answer,
                    "key_concepts": parsed_response.get("key_concepts", []),
                    "follow_up_questions": parsed_response.get("follow_up_questions", [])
                },
                "session_id": session_id,
                "error": None,
                "token_usage": str(self.get_total_token_usage())
            }

        except Exception as e:
            self.logger.error(f"Error generating chat response: {str(e)}")
            return {
                "title": "Error Session",
                "content": {
                    "answer": "Failed to generate response",
                    "key_concepts": [],
                    "follow_up_questions": []
                },
                "session_id": session_id if session_id else None,
                "error": f"Chat response generation failed: {str(e)}",
                "token_usage": str(self.get_total_token_usage())
            }

    def generate_notes(self, subject: str, topic: str, grade: Optional[int] = None, unit: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate comprehensive study notes with examples and explanations.

        Args:
            subject (str): Subject area
            topic (str): Specific topic for note generation
            grade (Optional[int]): Grade level
            unit (Optional[str]): Unit/chapter identifier

        Returns:
            Dict[str, Any]: Structured notes with validation results
        """
        try:
            # Get refined context for note generation
            context_response = self.context_agent.query_db(
                subject=subject,
                question=f"Generate detailed comprehensive notes about {topic}",
                grade=grade,
                unit=unit,
                type_req="notes"
            )
            
            if context_response.error:
                return {"error": context_response.error}

            # Get subject-specific rules before creating the prompt
            subject_rules = self._get_subject_rules(subject)
            
            # Enhanced note generation prompt with more detailed structure
            prompt = PromptTemplate.from_template("""
                Generate comprehensive educational notes on the topic based on the provided context.
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
                            "question": "Review question",
                            "key_points": ["Point 1", "Point 2"],
                            "suggested_answer": "Detailed answer"
                        }}
                    ]
                }}

                Context: {context}
                Topic: {topic}
                Subject Rules: {rules}
                
                Ensure to:
                1. Provide detailed explanations for each concept
                2. Include multiple examples with varying difficulty levels
                3. Address common misconceptions and mistakes
                4. Connect theoretical knowledge with practical applications
                5. Include both basic and advanced content where appropriate
            """)

            chain = prompt | self.llm | StrOutputParser()

            response = chain.invoke({
                "context": _format_docs(context_response.context),
                "topic": topic,
                "rules": self._get_subject_rules(subject)
            })

            parsed_response = self._parse_llm_response(str(response))

            # Validate notes content with enhanced required sections
            required_sections = [
                "title", "overview", "learning_objectives", "key_concepts",
                "worked_examples", "practice_problems", "real_world_applications"
            ]
            if not all(key in parsed_response for key in required_sections):
                raise ValueError("Generated notes missing required sections")

            # Add enhanced metadata
            parsed_response["metadata"] = {
                "subject": subject,
                "topic": topic,
                "grade": grade,
                "unit": unit,
                "generated_at": datetime.now().isoformat(),
                "complexity_level": "comprehensive",
                "estimated_study_time": "45-60 minutes",
                "version": "2.0"
            }

            self.record_token_usage(
                f"{_format_docs(context_response.context)}\n{subject_rules}",
                str(parsed_response)
            )

            return {
                "notes": parsed_response,
                "error": None,
                "token_usage": str(self.get_total_token_usage())
            }

        except Exception as e:
            self.logger.error(f"Error generating notes: {str(e)}")
            return {
                "error": f"Notes generation failed: {str(e)}",
                "token_usage": str(self.get_total_token_usage())
            }

    def evaluate_practice_answer(self, subject: str, question: Dict[str, Any], student_answer: str) -> Dict[str, Any]:
        try:
            # Input validation remains the same
            if not isinstance(question, dict) or 'question' not in question:
                raise ValueError("Invalid question format")
            
            if not student_answer.strip():
                raise ValueError("Empty student answer")

            # Get relevant context
            context_response = self.context_agent.query_db(
                subject=subject,
                question=question["question"],
                type_req="chat"
            )
            
            if context_response.error:
                raise ValueError(f"Failed to get context: {context_response.error}")

            # Get subject-specific rules before creating the prompt
            subject_rules = self._get_subject_rules(subject)
            
            # Simplified and more explicit prompt
            prompt = PromptTemplate.from_template("""
                Evaluate this student's answer for a mathematics problem.

                SUBJECT: {subject}
                QUESTION: {question}
                STUDENT'S ANSWER: {student_answer}
                EXPECTED APPROACH: {solution_approach}
                CONTEXT: {context}

                Your task is to evaluate the student's answer and provide detailed feedback.
                Format your response EXACTLY as shown in the example below:

                {{
                    "is_correct": true,
                    "score": 0.85,
                    "feedback": "Your solution is mostly correct. You correctly factored the equation...",
                    "improvement_suggestions": [
                        "Show your intermediate steps",
                        "Explain why you chose factoring"
                    ],
                    "correct_solution": "Step 1: Rearrange to standard form: x^2 - 5x + 6 = 0\\nStep 2: Factor: (x-2)(x-3) = 0\\nStep 3: Solve: x = 2 or x = 3",
                    "misconceptions": [
                        "No major misconceptions identified"
                    ],
                    "key_points_missed": [
                        "Did not verify solutions"
                    ],
                    "strengths": [
                        "Correct factoring technique",
                        "Arrived at right answer"
                    ]
                }}

                Remember:
                1. Keep all JSON fields
                2. Score must be between 0 and 1
                3. Arrays must contain at least one item
                4. Use specific, actionable feedback
                5. Maintain proper JSON format
            """)

            chain = prompt | self.llm | StrOutputParser()

            response = chain.invoke({
                "subject": subject,
                "question": question["question"],
                "solution_approach": question.get("solution_approach", ""),
                "student_answer": student_answer,
                "context": _format_docs(context_response.context)
            })

            # Parse response with enhanced error handling
            try:
                # Clean the response string
                response_str = str(response).strip()
                # Extract JSON if embedded in other text
                start_idx = response_str.find('{')
                end_idx = response_str.rfind('}') + 1
                if start_idx != -1 and end_idx > start_idx:
                    json_str = response_str[start_idx:end_idx]
                else:
                    raise ValueError("No JSON object found in response")

                parsed_response = json.loads(json_str)
                
                # Validate and ensure all required fields with proper types
                evaluation_result = {
                    "is_correct": bool(parsed_response.get("is_correct", False)),
                    "score": float(max(0, min(1, float(parsed_response.get("score", 0))))),
                    "feedback": self._clean_unicode(str(parsed_response.get("feedback", "No detailed feedback available"))).strip(),
                    "improvement_suggestions": [
                        self._clean_unicode(str(suggestion)) 
                        for suggestion in parsed_response.get("improvement_suggestions", ["Review your approach"])
                    ],
                    "correct_solution": self._clean_unicode(str(parsed_response.get("correct_solution", "Solution not provided"))).strip(),
                    "misconceptions": [
                        self._clean_unicode(str(misc)) 
                        for misc in parsed_response.get("misconceptions", ["No misconceptions identified"])
                    ],
                    "key_points_missed": [
                        self._clean_unicode(str(point)) 
                        for point in parsed_response.get("key_points_missed", ["None identified"])
                    ],
                    "strengths": [
                        self._clean_unicode(str(strength)) 
                        for strength in parsed_response.get("strengths", ["Areas of strength not identified"])
                    ],
                    "token_usage": str(self.get_total_token_usage())
                }

                # Ensure non-empty arrays
                for key in ["improvement_suggestions", "misconceptions", "key_points_missed", "strengths"]:
                    if not evaluation_result[key]:
                        evaluation_result[key] = ["None identified"]

                # Record token usage for this operation
                self.record_token_usage(
                    f"{_format_docs(context_response.context)}\n{subject_rules}",
                    str(parsed_response)
                )

                return evaluation_result

            except json.JSONDecodeError as e:
                self.logger.error(f"JSON parsing error: {str(e)}\nResponse: {response_str}")
                raise ValueError(f"Invalid JSON format in response: {str(e)}")
            except Exception as e:
                self.logger.error(f"Response parsing error: {str(e)}")
                raise ValueError(f"Failed to parse evaluation response: {str(e)}")

        except Exception as e:
            self.logger.error(f"Evaluation error: {str(e)}")
            return {
                "error": str(e),
                "is_correct": False,
                "score": 0,
                "feedback": "Could not evaluate answer due to system error",
                "improvement_suggestions": ["Please try again"],
                "correct_solution": "Unable to provide solution at this time",
                "misconceptions": ["Evaluation failed"],
                "key_points_missed": ["Evaluation failed"],
                "strengths": ["Evaluation failed"],
                "token_usage": str(self.get_total_token_usage())
            }

# Example usage
if __name__ == "__main__":
    agent = GenerationAgent()
    
    # Generate MCQs
    # mcqs = agent.generate_mcqs(
    #     subject="history",
    #     grade=9,
    #     unit="3",
    #     num_questions=10
    # )
    # print("MCQs:", json.dumps(mcqs, indent=2))

    notes = agent.generate_notes(
        subject="history",
        topic="Major Factors for the Rise of the Aksumite Kingdom",
        grade=9,
        unit="3"
    )
    print("Notes:", json.dumps(notes, indent=2))

    # # Generate Flashcards
    # flashcards = agent.generate_flashcards(
    #     subject="chemistry",
    #     grade=9,
    #     unit="3",
    #     num_cards=10
    # )
    # print("Flashcards:", json.dumps(flashcards, indent=2))

    # # Generate Flashcards with topic
    # flashcards_with_topic = agent.generate_flashcards(
    #     subject="english",
    #     num_cards=10,
    #     topic="Verb strings identification"
    # )
    # print("Flashcards with Topic:", json.dumps(flashcards_with_topic, indent=2))

    # # Test chat functionality
    # session_id = agent.create_chat_session("maths", "Math Help")

    # questions = [
    #     "Can you explain what a quadratic equation is?",
    # ]

    # for question in questions:
    #     response = agent.chat_response("maths", question, session_id)
    #     print("Response: ", response)

    # # Test answer evaluation
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
    # print("\nAnswer Evaluation:", json.dumps(evaluation, indent=2))
