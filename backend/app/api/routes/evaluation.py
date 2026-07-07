import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import EvaluateAnswerRequest
from app.schemas.responses import EvaluateAnswerResponse
from app.security.rate_limiter import limiter
from app.services.generation import run_evaluate_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluate", tags=["Evaluation"])


@router.post("", response_model=EvaluateAnswerResponse)
@limiter.limit("300/day")
@limiter.limit("20/minute")
async def evaluate_answer(
    request: Request,
    body: EvaluateAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvaluateAnswerResponse:
    result = await run_evaluate_answer(
        subject=body.subject,
        question=body.question,
        student_answer=body.student_answer,
        note=body.note,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    # Persist the attempt where the grade is produced — client-side logging would
    # lose writes on page leave and let clients assert correct:true unverified.
    # Best-effort: analytics must never break the evaluation response.
    try:
        await crud.record_attempts(db, current_user.id, [{
            "subject": body.subject, "grade": body.grade, "unit": body.unit,
            "topic": body.topic, "correct": result.get("is_correct", False),
            "source": "review", "score": result.get("score"),
        }])
    except Exception:
        logger.exception("failed to record review attempt")

    return EvaluateAnswerResponse(
        is_correct=result.get("is_correct", False),
        score=result.get("score", 0.0),
        feedback=result.get("feedback", ""),
        improvement_suggestions=result.get("improvement_suggestions", []),
        correct_solution=result.get("correct_solution", []),
        misconceptions=result.get("misconceptions", []),
        key_points_missed=result.get("key_points_missed", []),
        strengths=result.get("strengths", []),
        token_usage=result.get("token_usage"),
    )
