import asyncio
import logging
import time
from typing import List, Optional
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from pymilvus import MilvusClient

from app.core.curriculum_validation import KNOWN_SUBJECTS, VALID_COMBINATIONS
from app.core.exceptions import OutOfContextError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COLLECTION_NAME = "smartstudy"
MILVUS_URI = "http://localhost:19530"


class RetrievalAgentError(Exception):
    pass


def _dedupe_similar(documents: List[Document], threshold: float = 0.75) -> List[Document]:
    """Drop near-duplicate chunks using word-shingle Jaccard similarity.

    CHUNK_OVERLAP=200 on CHUNK_SIZE=1000 (dataloader.py) means adjacent chunks from the
    same source share ~20% of their text verbatim, and top-k retrieval on a single query
    embedding tends to pull several such neighbours back together. Milvus results arrive
    ranked by relevance, so the first (highest-similarity) chunk in a near-duplicate
    cluster is kept and later ones are dropped — trims redundant context before it reaches
    the generation prompt, cheaper than reranking with a second embedding call.
    ponytail: O(k^2) shingle comparison — fine at k<=75 (current retrieval sizes); switch
    to a real reranker/MMR if k grows into the hundreds.
    """
    kept: List[Document] = []
    kept_shingles: List[set] = []
    for doc in documents:
        words = doc.page_content.split()
        shingles = {" ".join(words[i:i + 5]) for i in range(max(1, len(words) - 4))}
        if any(
            shingles and other and len(shingles & other) / len(shingles | other) >= threshold
            for other in kept_shingles
        ):
            continue
        kept.append(doc)
        kept_shingles.append(shingles)
    return kept


class RetrievalAgent:
    MAX_RETRIES = 3
    RETRY_DELAY = 1

    VALID_COMBINATIONS = VALID_COMBINATIONS
    KNOWN_SUBJECTS = KNOWN_SUBJECTS

    def __init__(self, milvus_uri: str = MILVUS_URI):
        self.client = MilvusClient(uri=milvus_uri)
        self.embeddings = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url="http://localhost:11434",
        )

    def _validate_subject_exists(self, subject: str) -> None:
        if subject not in self.KNOWN_SUBJECTS:
            raise OutOfContextError(
                f"Subject '{subject}' is not available. "
                f"Valid subjects: {', '.join(sorted(self.KNOWN_SUBJECTS))}.",
                valid_options={"subjects": sorted(self.KNOWN_SUBJECTS)},
            )

    def _validate_request(self, subject: str, grade: Optional[int], unit: Optional[str]) -> None:
        if grade is not None:
            if grade not in self.VALID_COMBINATIONS:
                raise OutOfContextError(
                    f"Grade {grade} is not available. Valid grades: 9, 10, 11, 12.",
                    valid_options={"grades": [9, 10, 11, 12]},
                )
            if subject not in self.VALID_COMBINATIONS[grade]:
                available = sorted(self.VALID_COMBINATIONS[grade].keys())
                raise OutOfContextError(
                    f"'{subject.title()}' is not offered in Grade {grade}. "
                    f"Available subjects for Grade {grade}: {', '.join(available)}.",
                    valid_options={"subjects": available},
                )
            if unit is not None:
                try:
                    unit_num = int(unit)
                except (ValueError, TypeError):
                    raise OutOfContextError(
                        "Unit must be a number.",
                        valid_options={},
                    )
                max_units = self.VALID_COMBINATIONS[grade][subject]
                if unit_num < 1 or unit_num > max_units:
                    raise OutOfContextError(
                        f"Unit {unit_num} does not exist for {subject.title()} Grade {grade}. "
                        f"Valid units are 1–{max_units}.",
                        valid_options={"units": list(range(1, max_units + 1))},
                    )

    def _build_filter(self, subject: str, grade: Optional[int], unit: Optional[str], type_req: str) -> str:
        parts = [f'subject == "{subject}"']
        # sat/english are cross-grade supplements with no grade/unit metadata, so never
        # filter on those fields for them.
        if subject not in ("sat", "english"):
            # Grade narrows both chat and quiz/notes retrieval when it is known — a Grade 9
            # student should not get Grade 12 content in chat answers.
            if grade is not None:
                parts.append(f'grade == "{grade}"')
            # Unit only narrows quiz/notes generation; chat stays grade-wide across units.
            if unit is not None and type_req not in ("chat",):
                parts.append(f'unit == "{unit}"')
        return " and ".join(parts)

    def _calculate_k(self, type_req: str, k_multiplier: float) -> int:
        base = 45
        if type_req == "notes":
            base = 60
        return int(base * k_multiplier)

    async def query_vector_store(
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
                _t = time.perf_counter()
                query_vector = await self.embeddings.aembed_query(question)
                logger.info("[retrieval] embed: %.2fs", time.perf_counter() - _t)

                k = self._calculate_k(type_req, k_multiplier)
                expr = self._build_filter(subject, grade, unit, type_req)

                _t = time.perf_counter()
                results = await asyncio.to_thread(
                    self.client.search,
                    collection_name=COLLECTION_NAME,
                    data=[query_vector],
                    limit=k,
                    filter=expr,
                    output_fields=["text", "grade", "subject", "unit", "source"],
                    search_params={"nprobe": 128},  # exhaustive search across all IVF clusters
                )
                logger.info("[retrieval] milvus-search (k=%d): %.2fs", k, time.perf_counter() - _t)

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

                before = len(documents)
                documents = _dedupe_similar(documents)
                logger.info(
                    "Retrieved %d documents for subject=%s (%d after near-dup filter)",
                    before, subject, len(documents),
                )
                return documents

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise RetrievalAgentError(
                        f"Failed to query Milvus after {self.MAX_RETRIES} attempts: {e}"
                    )
