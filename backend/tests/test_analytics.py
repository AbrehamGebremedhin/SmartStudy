"""Attempt logging + per-unit mastery aggregation."""
import pytest


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
