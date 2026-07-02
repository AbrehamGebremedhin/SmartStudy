import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from RetrievalAgent import RetrievalAgent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@dataclass
class RefinementResponse:
    context: object  # List[Document] or str
    parsed_answer: Dict[str, Any]
    summary: Dict[str, Any]
    error: Optional[str] = None
    token_usage: Optional[str] = None


class ContextRefinementError(Exception):
    pass


class ContextRefinementAgent:
    """Thin wrapper around RetrievalAgent: validates request params and returns
    retrieved documents. No LLM call — vector-search retrieval is all that's
    needed here; per-request extraction (keypoints/areas/sections) was dropped
    as a dead sequential round-trip that nothing downstream consumed beyond the
    documents themselves. See generate_notes for the equivalent precedent."""

    def __init__(self):
        load_dotenv("./.env")
        self.logger = logging.getLogger(__name__)
        try:
            self.retrieval_agent = RetrievalAgent()
        except Exception as e:
            raise ContextRefinementError(f"Failed to initialize services: {str(e)}")

    def validate_inputs(self, subject: str, question: str, grade: Optional[int] = None, unit: Optional[str] = None) -> None:
        if not all([subject, question]):
            raise ValueError("Subject and question must not be empty")
        if grade is not None and (not isinstance(grade, int) or grade < 1 or grade > 12):
            raise ValueError("Grade must be an integer between 1 and 12")
        if not isinstance(subject, str) or not isinstance(question, str):
            raise ValueError("Subject and question must be strings")

    async def query_documents_only(
        self,
        subject: str,
        question: str,
        grade: Optional[int] = None,
        unit: Optional[str] = None,
        type_req: str = "quiz",
    ) -> RefinementResponse:
        """Vector DB retrieval only — no LLM extraction. Used by every generation type."""
        try:
            self.validate_inputs(subject, question, grade, unit)
            if type_req == "notes":
                context = await self.retrieval_agent.query_vector_store(
                    subject, question, grade, unit, "notes", k_multiplier=1.25
                )
            else:
                context = await self.retrieval_agent.query_vector_store(
                    subject, question, grade, unit, type_req
                )
            if not context:
                return RefinementResponse(
                    context="", parsed_answer={}, summary={},
                    error="No relevant documents found"
                )
            return RefinementResponse(
                context=context,
                parsed_answer={"areas": [], "key_concepts": []},
                summary={},
            )
        except ValueError as e:
            self.logger.error(f"Validation error: {str(e)}")
            return RefinementResponse(context="", parsed_answer={}, summary={}, error=f"Validation error: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error in query_documents_only: {str(e)}")
            return RefinementResponse(context="", parsed_answer={}, summary={}, error=f"Processing error: {str(e)}")
