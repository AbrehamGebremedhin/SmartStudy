import logging
from typing import List, Optional
from time import sleep
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from pymilvus import MilvusClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COLLECTION_NAME = "smartstudy"
MILVUS_URI = "http://localhost:19530"


class RetrievalAgentError(Exception):
    pass


class RetrievalAgent:
    MAX_RETRIES = 3
    RETRY_DELAY = 1

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

    KNOWN_SUBJECTS = {
        "biology", "chemistry", "civics", "economics", "english",
        "general_business", "geography", "history", "maths", "physics", "sat"
    }

    def __init__(self, milvus_uri: str = MILVUS_URI):
        self.client = MilvusClient(uri=milvus_uri)
        self.embeddings = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url="http://localhost:11434",
        )

    def _validate_subject_exists(self, subject: str) -> None:
        if subject not in self.KNOWN_SUBJECTS:
            raise ValueError(f"Subject '{subject}' does not exist in the records")

    def _validate_request(self, subject: str, grade: Optional[int], unit: Optional[str]) -> None:
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

    def _build_filter(self, subject: str, grade: Optional[int], unit: Optional[str], type_req: str) -> str:
        parts = [f'subject == "{subject}"']
        if type_req not in ("chat",) and subject not in ("sat", "english"):
            if grade is not None:
                parts.append(f'grade == "{grade}"')
            if unit is not None:
                parts.append(f'unit == "{unit}"')
        return " and ".join(parts)

    def _calculate_k(self, type_req: str, k_multiplier: float) -> int:
        base = 45
        if type_req == "notes":
            base = 60
        return int(base * k_multiplier)

    def query_vector_store(
        self,
        subject: str,
        question: str,
        grade: Optional[int] = None,
        unit: Optional[str] = None,
        type_req: str = "chat",
        k_multiplier: float = 1.0,
    ) -> List[Document]:
        if not question.strip():
            raise ValueError("Question cannot be empty")

        subject = subject.lower().strip()
        self._validate_subject_exists(subject)

        if type_req != "chat" and subject not in ("sat", "english"):
            self._validate_request(subject, grade, unit)

        for attempt in range(self.MAX_RETRIES):
            try:
                query_vector = self.embeddings.embed_query(question)
                k = self._calculate_k(type_req, k_multiplier)
                expr = self._build_filter(subject, grade, unit, type_req)

                results = self.client.search(
                    collection_name=COLLECTION_NAME,
                    data=[query_vector],
                    limit=k,
                    filter=expr,
                    output_fields=["text", "grade", "subject", "unit", "source"],
                    search_params={"nprobe": 128},  # exhaustive search across all IVF clusters
                )

                documents = [
                    Document(
                        page_content=hit["entity"]["text"],
                        metadata={
                            "grade": hit["entity"].get("grade", ""),
                            "subject": hit["entity"].get("subject", ""),
                            "unit": hit["entity"].get("unit", ""),
                            "source": hit["entity"].get("source", ""),
                        },
                    )
                    for hit in results[0]
                ]

                logger.info(f"Retrieved {len(documents)} documents for subject={subject}")
                return documents

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    sleep(self.RETRY_DELAY)
                else:
                    raise RetrievalAgentError(
                        f"Failed to query Milvus after {self.MAX_RETRIES} attempts: {e}"
                    )
