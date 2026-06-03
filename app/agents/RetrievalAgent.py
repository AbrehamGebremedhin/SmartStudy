import os
import logging
from typing import List, Dict, Optional
from functools import lru_cache
from time import sleep
from dotenv import load_dotenv
from langchain_astradb import AstraDBVectorStore
from astrapy.info import CollectionVectorServiceOptions

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RetrievalAgentError(Exception):
    """Custom exception for handling RetrievalAgent-specific errors."""
    pass

class RetrievalAgent:
    """
    A class responsible for retrieving relevant educational content from vector databases.
    
    This agent handles sophisticated content retrieval operations, including context-aware
    searching, grade-appropriate content filtering, and subject-specific optimizations.
    It includes robust error handling and retry mechanisms for database operations.

    Attributes:
        MAX_RETRIES (int): Maximum number of retry attempts for database operations
        RETRY_DELAY (int): Delay in seconds between retry attempts
        VALID_COMBINATIONS (Dict): Mapping of valid grade-subject-unit combinations
        application_token (str): Token for AstraDB authentication
        endpoint (str): AstraDB API endpoint
        nvidia_vectorize_options (CollectionVectorServiceOptions): Vector service configuration

    Methods:
        query_vector_store: Main method for retrieving relevant content
        calculate_k: Determines optimal number of results to retrieve
        get_vector_store: Manages vector store connections with caching

    Notes:
        - Uses AstraDB for vector storage and retrieval
        - Implements caching for improved performance
        - Handles subject-specific content retrieval rules
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 1  # seconds
    
    # Add valid combinations mapping
    VALID_COMBINATIONS = {
        12: {
            'biology': 6, 'chemistry': 5, 'civics': 10, 'economics': 8,
            'english': 10, 'general_business': 4, 'geography': 8,
            'history': 9, 'maths': 9, 'physics': 5
        },
        11: {
            'biology': 6, 'chemistry': 6, 'civics': 11, 'economics': 6,
            'english': 10, 'general_business': 4, 'geography': 8,
            'history': 9, 'maths': 8, 'physics': 7
        },
        10: {
            'biology': 5, 'chemistry': 6, 'civics': 8, 'economics': 8,
            'english': 10, 'geography': 8, 'history': 9, 'maths': 7,
            'physics': 6
        },
        9: {
            'biology': 6, 'chemistry': 5, 'civics': 8, 'economics': 7,
            'english': 12, 'geography': 8, 'history': 9, 'maths': 9,
            'physics': 7
        }
    }

    def __init__(self):
        """Initialize the RetrievalAgent with configuration and vector store settings."""
        self._load_config()
        self._initialize_vector_options()
        
    def _load_config(self) -> None:
        """Load and validate environment configuration."""
        load_dotenv("./config.env")
        self.application_token = os.getenv("ASTRA_DB_APPLICATION_TOKEN")
        self.endpoint = os.getenv("COMBINED_SUBJECTS_ASTRA_DB_API_ENDPOINT")
        
        if not self.application_token or not self.endpoint:
            raise RetrievalAgentError("Missing required environment variables")

    def _initialize_vector_options(self) -> None:
        """Initialize vector store options and configuration."""
        self.nvidia_vectorize_options = CollectionVectorServiceOptions(
            provider="nvidia",
            model_name="NV-Embed-QA",
        )
        
        self.no_records = {
            "biology": 10075,
            "chemistry": 13085,
            "civics": 9190,
            "economics": 15585,
            "english": 23055,
            "general_business": 6570,
            "geography": 11581,
            "history": 13855,
            "maths": 13771,
            "physics": 9484,
            "sat": 14870
        }

    def _normalize_subject(self, subject: str) -> str:
        """
        Normalize subject name to standard format for database operations.

        Converts subject names to a standardized format used in the vector database.
        Handles case normalization and adds required prefixes.

        Args:
            subject (str): Raw subject name input

        Returns:
            str: Normalized subject name in uppercase with COMBINED_ prefix

        Examples:
            >>> _normalize_subject("math")
            "COMBINED_MATH"
            >>> _normalize_subject("General Science")
            "COMBINED_GENERAL_SCIENCE"
        """
        subject = subject.lower().strip()
        return f"COMBINED_{subject.upper()}"

    @lru_cache(maxsize=32)
    def get_vector_store(self, subject: str) -> AstraDBVectorStore:
        """
        Get or create a cached vector store instance for a subject.

        Args:
            subject (str): The normalized subject name

        Returns:
            AstraDBVectorStore: Vector store instance for the subject

        Raises:
            RetrievalAgentError: If vector store initialization fails
        """
        try:
            return AstraDBVectorStore(
                collection_name=subject,
                api_endpoint=self.endpoint,
                token=self.application_token,
                collection_vector_service_options=self.nvidia_vectorize_options,
            )
        except Exception as e:
            logger.error(f"Failed to initialize vector store for {subject}: {e}")
            raise RetrievalAgentError(f"Vector store initialization failed: {e}")

    def calculate_k(self, subject: str) -> int:
        """
        Calculate optimal number of results to retrieve based on subject records.

        Determines the appropriate number of results to fetch from the vector store
        based on the total number of records available for a subject and other
        optimization factors.

        Args:
            subject (str): Normalized subject name

        Returns:
            int: Optimal number of results to retrieve

        Notes:
            - Adjusts result count based on subject-specific characteristics
            - Uses predefined thresholds for different record count ranges
            - Optimized for educational content retrieval
        """
        subject_key = subject.replace('COMBINED_', '').lower()
        total_records = self.no_records.get(subject_key, 10000)
        
        if total_records < 7000:
            return 35
        elif total_records < 12000:
            return 45
        elif total_records < 16000:
            return 55
        return 60

    def _validate_request(self, subject: str, grade: Optional[int], unit: Optional[str]) -> None:
        """
        Validate if the subject, grade and unit combination is valid.
        
        Args:
            subject (str): Subject name
            grade (Optional[int]): Grade level
            unit (Optional[str]): Unit number

        Raises:
            ValueError: If the combination is invalid
        """
        if subject.startswith('COMBINED_'):
            subject = subject[9:].lower()

        if grade is not None:
            if grade not in self.VALID_COMBINATIONS:
                raise ValueError(f"Invalid grade: {grade}. Must be between 9-12")
            
            if subject not in self.VALID_COMBINATIONS[grade]:
                raise ValueError(f"Invalid subject '{subject}' for grade {grade}")
            
            if unit is not None:
                try:
                    unit_num = int(unit)
                    max_units = self.VALID_COMBINATIONS[grade][subject]
                    if unit_num < 1 or unit_num > max_units:
                        raise ValueError(
                            f"Invalid unit {unit} for {subject} grade {grade}. "
                            f"Must be between 1 and {max_units}"
                        )
                except ValueError as e:
                    if "invalid literal for int()" in str(e):
                        raise ValueError("Unit must be a number")
                    raise

    def _validate_subject_exists(self, subject: str) -> None:
        """
        Validate if the subject exists in the predefined records.

        Args:
            subject (str): Normalized subject name

        Raises:
            ValueError: If the subject does not exist
        """
        subject_key = subject.replace('COMBINED_', '').lower()
        if subject_key not in self.no_records:
            raise ValueError(f"Subject '{subject_key}' does not exist in the records")

    def query_vector_store(self, subject: str, question: str, grade: Optional[int] = None, 
                         unit: Optional[str] = None, type_req: str = "chat",
                         k_multiplier: float = 1.0) -> List:
        """
        Query the vector store for relevant educational content with advanced filtering.

        Performs sophisticated content retrieval with support for various content types,
        grade levels, and subject-specific optimizations. Includes retry logic and
        error handling for robust operation.

        Args:
            subject (str): Subject area to query
            question (str): The query question or prompt
            grade (Optional[int]): Grade level for content filtering
            unit (Optional[str]): Unit/chapter identifier
            type_req (str): Type of request ("chat", "mcq", "notes")
            k_multiplier (float): Multiplier for number of results to retrieve

        Returns:
            List: List of relevant documents from the vector store

        Raises:
            RetrievalAgentError: If query fails after maximum retries
            ValueError: If question is empty or inputs are invalid

        Notes:
            - Implements automatic retry logic for failed queries
            - Optimizes result count based on request type and subject
            - Filters results based on grade level and unit when applicable
        """
        if not question.strip():
            raise ValueError("Question cannot be empty")

        subject = self._normalize_subject(subject)
        
        # Validate subject existence
        self._validate_subject_exists(subject)
        
        # Add validation for non-chat requests
        if type_req != "chat" and subject.lower() not in ["combined_sat", "combined_english"]:
            self._validate_request(subject, grade, unit)

        for attempt in range(self.MAX_RETRIES):
            try:
                vector_store = self.get_vector_store(subject=subject)
                # Apply multiplier to base k value
                k = int(self.calculate_k(subject) * k_multiplier)
                
                filter_params = {"subject": subject}
                if type_req != "chat" and subject.lower() not in ["combined_sat", "combined_english"]:
                    filter_params.update({
                        "unit": unit,
                        "grade": grade
                    })

                results = vector_store.similarity_search_with_score(
                    question,
                    k=k,
                    filter=filter_params if filter_params else None
                )
                
                documents = [doc for doc, _ in results]
                logger.info(f"Successfully retrieved {len(documents)} documents for {subject}")
                return documents

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    sleep(self.RETRY_DELAY)
                else:
                    raise RetrievalAgentError(f"Failed to query vector store after {self.MAX_RETRIES} attempts: {e}")