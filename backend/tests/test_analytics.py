"""Attempt logging + per-unit mastery aggregation."""
import uuid

import pytest

from app.db import crud


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
