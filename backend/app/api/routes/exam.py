from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import ExamQuestion, User
from app.security.rate_limiter import limiter

router = APIRouter(prefix="/exam", tags=["Past Exams"])


def _serialize(q: ExamQuestion) -> dict:
    return {
        "id": str(q.id),
        "subject": q.subject,
        "year": q.year,
        "exam_name": q.exam_name,
        "number": q.number,
        "grade": q.grade,
        "unit": q.unit,
        "topic": q.topic,
        "question": q.question,
        "passage": q.passage,
        "question_image_url": q.question_image_url,
        "options": q.options,  # [{letter, text, image_url}]
        "correct_answer": q.correct_answer,
        "correct_explanations": q.correct_explanations,
        "incorrect_explanations": q.incorrect_explanations,
        "workout_steps": q.workout_steps,
        "difficulty": q.difficulty,
    }


@router.get("/subjects")
@limiter.limit("120/minute")
async def list_subjects(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await crud.get_exam_subjects(db)
    return {"subjects": [{"subject": s, "count": n} for s, n in rows]}


@router.get("/{subject}/years")
@limiter.limit("120/minute")
async def list_years(
    request: Request,
    subject: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"years": await crud.get_exam_years(db, subject.lower())}


@router.get("/practice")
@limiter.limit("60/minute")
async def practice(
    request: Request,
    subject: str,
    year: str | None = None,
    grade: int | None = None,
    unit: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    include_review: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    questions = await crud.get_exam_questions(
        db, subject.lower(), year=year, grade=grade, unit=unit,
        limit=limit, include_review=include_review,
    )
    return {"questions": [_serialize(q) for q in questions]}
