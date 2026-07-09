"""Attempt logging + per-unit mastery aggregation."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db import crud
from app.db.models import QuestionAttempt


@pytest.mark.asyncio
async def test_attempts_and_mastery(client):
    # Empty to start.
    assert (await client.get("/api/analytics/mastery")).json() == []

    # Log a batch: biology unit 1 = 1/3 correct, unit 2 = 2/2 correct.
    attempts = [
        {"subject": "biology", "grade": 12, "unit": "1", "topic": "Cells", "correct": True},
        {"subject": "biology", "grade": 12, "unit": "1", "topic": "Cells", "correct": False},
        {"subject": "biology", "grade": 12, "unit": "1", "topic": "DNA", "correct": False},
        {"subject": "biology", "grade": 12, "unit": "2", "topic": "Ecology", "correct": True},
        {"subject": "biology", "grade": 12, "unit": "2", "topic": "Ecology", "correct": True},
    ]
    res = await client.post("/api/analytics/attempts", json={"attempts": attempts})
    assert res.status_code == 204

    rows = (await client.get("/api/analytics/mastery?subject=biology")).json()
    assert len(rows) == 2
    # Weakest first: unit 1 at 33% before unit 2 at 100%.
    assert rows[0]["unit"] == "1"
    assert rows[0]["total"] == 3 and rows[0]["correct"] == 1 and rows[0]["accuracy"] == 33
    assert rows[1]["unit"] == "2"
    assert rows[1]["accuracy"] == 100

    # Subject filter excludes others.
    assert (await client.get("/api/analytics/mastery?subject=physics")).json() == []


@pytest.mark.asyncio
async def test_empty_batch_is_noop(client):
    res = await client.post("/api/analytics/attempts", json={"attempts": []})
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_source_semantics(client, db_session, test_user):
    """source/question_id/score columns: mastery excludes review+drill (but keeps
    legacy NULL rows), by_source splits practice vs mock, trends buckets every
    source, and clients can't claim source=review (server-side only)."""
    attempts = [
        {"subject": "maths", "grade": 12, "unit": "3", "correct": True, "source": "mcq"},
        {"subject": "maths", "grade": 12, "unit": "3", "correct": False, "source": "mcq"},
        {"subject": "maths", "grade": 12, "unit": "3", "correct": False, "source": "exam",
         "question_id": str(uuid.uuid4())},
        {"subject": "maths", "grade": 12, "unit": "3", "correct": True},  # legacy client, no source
        {"subject": "maths", "grade": 12, "unit": "3", "correct": True, "source": "drill"},
    ]
    assert (await client.post("/api/analytics/attempts", json={"attempts": attempts})).status_code == 204
    # Review rows are written server-side by the evaluate route; simulate one.
    await crud.record_attempts(db_session, test_user.id, [
        {"subject": "maths", "grade": 12, "unit": "3", "correct": True, "source": "review", "score": 0.9},
    ])

    # Mastery: drill + review excluded, legacy NULL kept → 2/4 = 50%.
    rows = (await client.get("/api/analytics/mastery?subject=maths")).json()
    assert len(rows) == 1
    assert rows[0]["total"] == 4 and rows[0]["correct"] == 2 and rows[0]["accuracy"] == 50

    # by_source: practice vs mock split, NULL as its own bucket.
    rows = (await client.get("/api/analytics/mastery?subject=maths&by_source=true")).json()
    by = {r["source"]: r for r in rows}
    assert by["mcq"]["total"] == 2 and by["mcq"]["accuracy"] == 50
    assert by["exam"]["total"] == 1 and by["exam"]["accuracy"] == 0
    assert by[None]["total"] == 1 and by[None]["accuracy"] == 100

    # Trends: every source shows, including review/drill and the NULL bucket.
    trows = (await client.get("/api/analytics/trends?days=7")).json()
    assert sum(r["total"] for r in trows) == 6
    assert {r["source"] for r in trows} == {"mcq", "exam", "drill", "review", None}

    # Clients may not claim source=review — that grade belongs to the backend.
    bad = [{"subject": "maths", "correct": True, "source": "review"}]
    assert (await client.post("/api/analytics/attempts", json={"attempts": bad})).status_code == 422

    # Retention: no flashcard reviews yet.
    assert (await client.get("/api/analytics/retention")).json() == []


@pytest.mark.asyncio
async def test_evaluate_logs_review_attempt(client, db_session, test_user):
    """The evaluate route persists the attempt server-side: source=review, the
    grader's score kept, visible in trends but never in mastery."""
    graded = {"is_correct": True, "score": 0.85, "feedback": "Good answer."}
    with patch("app.api.routes.evaluation.run_evaluate_answer", new=AsyncMock(return_value=graded)):
        res = await client.post("/api/evaluate", json={
            "subject": "biology", "question": {"question": "What is a cell?"},
            "student_answer": "The basic structural unit of life.",
            "grade": 12, "unit": "1", "topic": "Cells",
        })
    assert res.status_code == 200

    # Table persists across tests in the session DB — scope to this test's user.
    row = (await db_session.execute(
        select(QuestionAttempt).where(QuestionAttempt.user_id == test_user.id)
    )).scalars().one()
    assert row.source == "review" and row.correct is True and float(row.score) == 0.85
    assert row.subject == "biology" and row.grade == 12 and row.unit == "1"

    # Recall-under-priming never reaches mastery…
    assert (await client.get("/api/analytics/mastery?subject=biology")).json() == []
    # …but does show in trends.
    trows = (await client.get("/api/analytics/trends?days=7")).json()
    assert len(trows) == 1 and trows[0]["source"] == "review" and trows[0]["total"] == 1


@pytest.mark.asyncio
async def test_chat_activity_rollup(client, db_session, test_user):
    """Chat distillate: upserts accumulate per (user, day, subject), concepts
    merge and dedupe, and the endpoint aggregates across days."""
    await crud.record_chat_activity(db_session, test_user.id, "physics", 12, ["Newton's laws", "Momentum"])
    await crud.record_chat_activity(db_session, test_user.id, "physics", 12, ["Momentum", "Friction"])
    await crud.record_chat_activity(db_session, test_user.id, "maths", 12, [])
    await db_session.commit()

    rows = (await client.get("/api/analytics/chat-context?days=7")).json()
    by = {r["subject"]: r for r in rows}
    assert by["physics"]["count"] == 2
    assert by["physics"]["concepts"] == ["Newton's laws", "Momentum", "Friction"]  # merged, deduped
    assert by["maths"]["count"] == 1 and by["maths"]["concepts"] == []
    assert rows[0]["subject"] == "physics"  # most-asked first
