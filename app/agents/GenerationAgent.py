import os
import functools
import random
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
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    key_concepts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "message": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.role == "assistant" and self.key_concepts:
            d["key_concepts"] = self.key_concepts
        return d

@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    messages: List[ChatMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    subject: str = ""
    grade: Optional[int] = None

    def add_message(self, role: str, content: str, key_concepts: Optional[List[str]] = None):
        self.messages.append(ChatMessage(
            role=role,
            content=content,
            key_concepts=key_concepts or [],
        ))

    def get_recent_context(self, max_messages: int = 10) -> str:
        """Return the last N messages formatted for the LLM, excluding the most recent user turn."""
        # Exclude the last message (current user question — passed separately via {question})
        prior = self.messages[:-1] if self.messages else []
        recent = prior[-max_messages:] if len(prior) > max_messages else prior
        return "\n".join(f"{m.role}: {m.content}" for m in recent)

    def get_history_as_list(self) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self.messages]

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
        # JSON mode — forces DeepSeek to always return valid JSON
        self._json_llm = self.llm.bind(response_format={"type": "json_object"})
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

    def create_chat_session(self, subject: str, initial_title: str = "New Chat",
                             grade: Optional[int] = None) -> str:
        """Create a new chat session and return its ID"""
        session = ChatSession(subject=subject, title=initial_title, grade=grade)
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
        if subject.lower() == "biology":
            return """
                - The questions with workout questions should contain workout steps
                - Use ^ in place of superscript and _ in place of subscript
                - Include step-by-step solutions where applicable
                BIOCHEMICAL ACCURACY RULES (apply to ALL explanations, not just the answer):
                - Electron transport chain: Complexes I, III, and IV pump protons across the inner
                  mitochondrial membrane. Complex II does NOT pump protons — never state otherwise.
                - Cofactor directionality: always name the cofactor as it exists at the START of
                  the reaction. Catabolic (oxidation) reactions consume NADH and produce NAD+;
                  do not write "NAD+ is used" for a reaction that oxidises NADH.
                - Phosphate transfer: direct phosphate transfer DOES occur in substrate-level
                  phosphorylation and coupled reactions (e.g., creatine kinase). Never write
                  "direct phosphate transfer does not occur" for these reactions.
                - When writing incorrect_explanations, verify that the reason given for an option
                  being wrong is itself biochemically accurate. A wrong-option explanation must
                  not teach incorrect biology while trying to dismiss the wrong choice.
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
            cleaned_response = response.strip()
            # Strip any markdown code fences the model may have added
            if cleaned_response.startswith("```"):
                cleaned_response = cleaned_response.split("```")[1]
                if cleaned_response.startswith("json"):
                    cleaned_response = cleaned_response[4:]
                cleaned_response = cleaned_response.strip()
            # Extract the outermost JSON object if the model added surrounding text
            start_idx = cleaned_response.find('{')
            end_idx = cleaned_response.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                cleaned_response = cleaned_response[start_idx:end_idx]

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

    def _redistribute_answer_positions(self, questions: List[Dict]) -> List[Dict]:
        """
        Physically reorder options arrays so correct answers are spread across A/B/C/D.
        Content is never changed — only which letter label the correct option receives.
        """
        n = len(questions)
        if n == 0:
            return questions

        # Build a balanced target sequence: equal counts of A B C D, shuffled
        base = n // 4
        targets = []
        for letter in ["A", "B", "C", "D"]:
            targets.extend([letter] * base)
        # Distribute the up-to-3 remainder
        for letter in ["A", "B", "C", "D"][: n % 4]:
            targets.append(letter)
        random.shuffle(targets)

        result = []
        for q, target in zip(questions, targets):
            current = q.get("correct_answer", "A")
            if current == target:
                result.append(q)
                continue

            options = list(q.get("options", []))
            # Parse "X) text" into {letter: text}
            content: Dict[str, str] = {}
            for opt in options:
                if len(opt) >= 3 and opt[1] == ")":
                    content[opt[0]] = opt[3:]
            if len(content) != 4:
                result.append(q)  # can't safely reorder, leave as-is
                continue

            # Swap the content at the two positions (transposition)
            content[current], content[target] = content[target], content[current]

            new_options = [f"{l}) {content[l]}" for l in ["A", "B", "C", "D"]]

            # incorrect_explanations: the key `target` (a wrong option that just moved
            # to position `current`) must be renamed to `current`.
            old_inc = dict(q.get("incorrect_explanations", {}))
            new_inc: Dict[str, str] = {}
            for key, explanation in old_inc.items():
                new_inc[current if key == target else key] = explanation

            q = dict(q)
            q["options"] = new_options
            q["correct_answer"] = target
            q["incorrect_explanations"] = new_inc
            result.append(q)

        return result

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

            prompt = PromptTemplate.from_template("""
                Generate {num_questions} {difficulty} multiple choice questions based on the following context.

                CONTEXT GROUNDING RULE: Every question, option, and explanation must be drawn
                exclusively from the provided context. You may elaborate on and clarify what the
                context contains, but do not introduce concepts, facts, examples, or details that
                do not appear in the context. If something is not in the context, do not include it.

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

                UNIQUE TOPICS RULE: Every question must test a different topic. Before writing each
                question, mentally list the topics already used. If a topic is already covered, choose
                a different one. No two questions may share the same topic label.

                Return a JSON object with this exact structure:
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
                            "B": "Reason why B is wrong",
                            "C": "Reason why C is wrong",
                            "D": "Reason why D is wrong"
                        }},
                        "workout_steps": "step-by-step solution if the question involves calculation or multi-step reasoning; null if not applicable",
                        "difficulty": "{difficulty}"
                    }}
                ]}}

                CRITICAL RULES for incorrect_explanations:
                - The dict must contain ONLY the three wrong option letters.
                - NEVER include the correct_answer key inside incorrect_explanations.
                - If correct_answer is "B", then incorrect_explanations must have keys "A", "C", "D" only.
                - If correct_answer is "C", then incorrect_explanations must have keys "A", "B", "D" only.

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
                "context": _format_docs(context_response.context),
                "areas": context_response.parsed_answer.get("areas", []),
                "num_questions": num_questions,
                "subject_rules": subject_rules,
                "difficulty": difficulty,
            }

            response = chain.invoke(invoke_args)
            parsed_response = self._parse_llm_response(str(response))

            validation_result = self.validation_agent.validate_mcqs(
                parsed_response.get("questions", []),
                context_response.context,
                context_response.parsed_answer.get("areas", [])
            )

            if validation_result["needs_replacement"]:
                replacement_count = len(validation_result["invalid_indices"])
                additional_response = chain.invoke({**invoke_args, "num_questions": replacement_count})
                additional_parsed = self._parse_llm_response(str(additional_response))
                valid_questions = validation_result["valid_mcqs"] + additional_parsed.get("questions", [])
            else:
                valid_questions = validation_result["valid_mcqs"]

            # Redistribute correct answers across A/B/C/D by reordering options arrays
            valid_questions = self._redistribute_answer_positions(valid_questions)

            # Normalise per-question fields the model sometimes gets wrong
            for q in valid_questions:
                q["difficulty"] = difficulty
                ws = q.get("workout_steps")
                if not ws or str(ws).strip().upper() in ("N/A", "NA", "NONE", "-", "NOT APPLICABLE", "NULL"):
                    q["workout_steps"] = None

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

            prompt = PromptTemplate.from_template("""
                Generate {num_cards} {difficulty} flashcards based on the following context.

                CONTEXT GROUNDING RULE: Every card must be drawn exclusively from the provided
                context. You may elaborate on and clarify what the context contains, but do not
                introduce concepts, facts, examples, or details that do not appear in the context.
                If something is not in the context, do not include it.

                FRONT SIDE RULE (critical): The front must be a single, short prompt — one sentence
                or one clear question, maximum 15 words. It must be instantly scannable. Do NOT write
                multi-sentence questions, comparisons between two things, or embedded context. If a
                concept requires comparison, put the comparison framing on the back, not the front.
                Good examples: "What is the discriminant?", "Define osmosis.", "Formula for kinetic energy?"
                Bad examples: "Compare Goldstein and Thomson and explain how one built on the other."

                BACK SIDE: The back may be as detailed as needed — full explanations, derivations,
                examples, and step-by-step reasoning are all welcome here.

                DIFFICULTY — {difficulty}:
                - For STEM: test formulas, derivations, multi-step processes, or conceptual reasoning
                - For humanities: test analytical frameworks, critical perspectives, or key arguments
                - Aim to test understanding and application, not rote memorisation

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

            for card in valid_cards:
                card["difficulty"] = difficulty

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

    def chat_response(self, subject: str, question: str, session_id: Optional[str] = None,
                      grade: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate contextual educational responses to student questions with chat history support.
        """
        try:
            # Get or create session
            session = None
            if session_id:
                session = self.active_sessions.get(session_id)
            if not session:
                session_id = self.create_chat_session(subject, grade=grade)
                session = self.active_sessions[session_id]
            elif grade is not None and session.grade is None:
                session.grade = grade

            # Capture history BEFORE adding the current question so the LLM prompt
            # gets prior exchanges via {chat_history} and the new question via {question}
            # without duplication.
            chat_history = session.get_recent_context()
            session.add_message("user", question)

            context_response = self.context_agent.query_db(
                subject=subject,
                question=question,
                grade=None,
                unit=None,
                type_req="chat"
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

                CONTEXT GROUNDING RULE: Base your answer on the provided reference material.
                You may explain and expand on what the material contains, but do not introduce
                facts, concepts, examples, or details that are not present in the reference
                material. If the reference material does not cover something the student asks,
                acknowledge that and redirect to what the material does cover — do not draw
                from general knowledge to fill the gap.

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
            response = chain.invoke({
                "context": _format_docs(context_response.context),
                "question": question,
                "keypoints": context_response.parsed_answer.get("keypoints", []),
                "chat_history": chat_history,
                "current_title": session.title,
                "subject": session.subject,
                "grade_line": f"\n{grade_line}" if grade_line else "",
            })

            parsed_response = self._parse_llm_response(str(response))

            if (session.title == "New Chat" or parsed_response.get("should_update_title", False)):
                new_title = parsed_response.get("title", "")
                if new_title and new_title != session.title:
                    session.title = new_title

            answer = parsed_response.get("answer", "No answer generated")
            key_concepts = parsed_response.get("key_concepts", [])
            session.add_message("assistant", answer, key_concepts=key_concepts)

            subject_rules = self._get_subject_rules(subject)
            self.record_token_usage(
                f"{_format_docs(context_response.context)}\n{subject_rules}",
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
                "token_usage": str(self.get_total_token_usage()),
            }

        except Exception as e:
            self.logger.error(f"Error generating chat response: {str(e)}")
            return {
                "title": "Error Session",
                "session_id": session_id if session_id else None,
                "conversation_history": session.get_history_as_list() if session else [],
                "current_response": None,
                "error": f"Chat response generation failed: {str(e)}",
                "token_usage": str(self.get_total_token_usage()),
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

                CONTEXT GROUNDING RULE: Every section — key concepts, examples, worked examples,
                theories, formulas, misconceptions — must be drawn exclusively from the provided
                context. You may elaborate on and deepen what the context contains, but do not
                introduce concepts, facts, examples, or details that do not appear in the context.
                The context is the grade-level curriculum material; your notes must stay within it.

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
                
                Subject: {subject}
                Subject Rules: {rules}

                Section guidance by subject type:

                formulas_and_equations:
                  - Maths, physics, chemistry: include all relevant equations with derivations
                  - Biology, economics: include only if quantitative formulas appear in the context; otherwise []
                  - Humanities (history, civics, geography, general_business, english): always []

                worked_examples:
                  - Maths, physics, chemistry: step-by-step problem → solution walkthroughs
                  - Biology: 2+ scenario-based walkthroughs (e.g., "A site is contaminated with mercury — walk through how a bioremediation engineer would approach it step-by-step, including decision points and expected outcomes"). Do NOT leave this as [].
                  - Economics: scenario analysis walkthroughs (policy decision → effects)
                  - Humanities: always []

                practice_problems:
                  - All science and maths subjects: include at Basic / Intermediate / Advanced levels
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

                Ensure to:
                1. Provide detailed explanations for each key concept — multiple paragraphs per concept
                2. Include multiple examples with varying difficulty levels
                3. Address common misconceptions and mistakes
                4. Connect theoretical knowledge with practical applications
                5. Include both basic and advanced content where appropriate
                6. Do not abbreviate or placeholder sections — write full content for every field
            """)

            chain = prompt | self._json_llm | StrOutputParser()

            response = chain.invoke({
                "context": _format_docs(context_response.context),
                "topic": topic,
                "subject": subject,
                "rules": self._get_subject_rules(subject),
            })

            parsed_response = self._parse_llm_response(str(response))

            # Core sections required for all subjects
            required_sections = [
                "title", "overview", "learning_objectives", "key_concepts",
                "real_world_applications",
            ]
            # Science subjects also need these sections present (may be [] for non-applicable cases)
            if subject.lower() in self.stem_subjects:
                required_sections += ["worked_examples", "practice_problems"]

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
                "version": "1.0"
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
            
            prompt = PromptTemplate.from_template("""
                Evaluate this student's answer.

                SUBJECT: {subject}
                QUESTION: {question}
                STUDENT'S ANSWER: {student_answer}
                EXPECTED APPROACH: {solution_approach}
                CONTEXT: {context}

                Your task is to evaluate the student's answer and provide feedback directly to the student.

                CONTEXT GROUNDING RULE: The correct solution steps, key points, and feedback must
                be grounded in the provided context and expected approach. Do not introduce
                alternative methods, concepts, or details that are outside the scope of what the
                context and solution approach cover.

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
                
                raw_solution = parsed_response.get("correct_solution", [])
                if isinstance(raw_solution, list):
                    correct_solution = [self._clean_unicode(str(s)) for s in raw_solution]
                else:
                    # Fallback: split on literal \n if model ignored the array instruction
                    correct_solution = [self._clean_unicode(s.strip()) for s in str(raw_solution).split("\\n") if s.strip()]

                # Record first so token_usage in the result reflects this call
                self.record_token_usage(
                    f"{_format_docs(context_response.context)}\n{subject_rules}",
                    str(parsed_response)
                )

                evaluation_result = {
                    "practice_question": question,
                    "student_answer": student_answer,
                    "is_correct": bool(parsed_response.get("is_correct", False)),
                    "score": float(max(0, min(1, float(parsed_response.get("score", 0))))),
                    "feedback": self._clean_unicode(str(parsed_response.get("feedback", "No detailed feedback available"))).strip(),
                    "improvement_suggestions": [
                        self._clean_unicode(str(s))
                        for s in parsed_response.get("improvement_suggestions", ["Review your approach"])
                        if str(s).strip()
                    ] or ["Review your approach"],
                    "correct_solution": correct_solution or ["Solution not provided"],
                    "misconceptions": [
                        self._clean_unicode(str(m))
                        for m in parsed_response.get("misconceptions", [])
                        if str(m).strip()
                    ],
                    "key_points_missed": [
                        self._clean_unicode(str(p))
                        for p in parsed_response.get("key_points_missed", [])
                        if str(p).strip()
                    ],
                    "strengths": [
                        self._clean_unicode(str(s))
                        for s in parsed_response.get("strengths", ["Areas of strength not identified"])
                        if str(s).strip()
                    ] or ["Areas of strength not identified"],
                    "token_usage": str(self.get_total_token_usage()),
                }

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
    mcqs = agent.generate_mcqs(
        subject="biology",
        grade=12,
        unit="3",
        num_questions=10
    )
    print("MCQs:", json.dumps(mcqs, indent=2, ensure_ascii=False))

    # notes = agent.generate_notes(
    #     subject="biology",
    #     topic="ATP synthesis in cellular respiration",
    #     grade=12,
    #     unit="3"
    # )
    # print("Notes:", json.dumps(notes, indent=2, ensure_ascii=False))

    # # Generate Flashcards
    # flashcards = agent.generate_flashcards(
    #     subject="chemistry",
    #     grade=9,
    #     unit="3",
    #     num_cards=10
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
