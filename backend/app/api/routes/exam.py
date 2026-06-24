from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import crud
from app.db.database import get_db
from app.db.models import ExamQuestion, User
from app.security.rate_limiter import limiter

router = APIRouter(prefix="/exam", tags=["Mock Exam"])

# Per-subject mock-exam spec: (question_count, minutes). Counts are the median size of a
# real EUEE single-subject paper in the scraped data; minutes approximate EUEE timing
# (~1.2 min/q, more for calculation-heavy maths/physics/chemistry).
EXAM_SPECS: dict[str, tuple[int, int]] = {
    "biology":   (100, 120),
    "chemistry": (80, 110),
    "physics":   (55, 90),
    "maths":     (65, 100),
    "english":   (100, 120),
    "civics":    (100, 110),
    "economics": (80, 90),
    "geography": (100, 110),
    "history":   (100, 110),
    "sat":       (60, 80),
}
DEFAULT_SPEC = (50, 75)


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
    out = []
    for s, _n in rows:
        q, mins = EXAM_SPECS.get(s, DEFAULT_SPEC)
        out.append({"subject": s, "num_questions": q, "minutes": mins})
    return {"subjects": out}


@router.get("/practice")
@limiter.limit("60/minute")
async def practice(
    request: Request,
    subject: str,
    year: str | None = None,
    grade: int | None = None,
    unit: str | None = None,
    limit: int | None = Query(None, ge=1, le=200),
    include_review: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    subj = subject.lower()
    spec_q, spec_min = EXAM_SPECS.get(subj, DEFAULT_SPEC)
    questions = await crud.get_exam_questions(
        db, subj, year=year, grade=grade, unit=unit,
        limit=limit or spec_q, include_review=include_review,
    )
    return {"questions": [_serialize(q) for q in questions],
            "num_questions": spec_q, "minutes": spec_min}
