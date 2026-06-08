from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.schemas.requests import EvaluateAnswerRequest
from app.schemas.responses import EvaluateAnswerResponse
from app.services.generation import run_evaluate_answer

router = APIRouter(prefix="/evaluate", tags=["Evaluation"])


@router.post("", response_model=EvaluateAnswerResponse)
async def evaluate_answer(
    request: EvaluateAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvaluateAnswerResponse:
    result = await run_evaluate_answer(
        subject=request.subject,
        question=request.question,
        student_answer=request.student_answer,
        note=request.note,
    )

    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

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
