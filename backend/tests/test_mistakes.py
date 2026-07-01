"""Mistake bank: record wrong questions, list them, resolve on mastery."""
import pytest


def _q(text="What is 2+2?"):
    return {
        "question": text,
        "options": [{"letter": "A", "text": "3"}, {"letter": "B", "text": "4"}],
        "correct_answer": "B",
        "correct_explanations": ["Because 2+2=4."],
        "incorrect_explanations": {"A": "3 is 2+1."},
        "topic": "Arithmetic",
    }


@pytest.mark.asyncio
async def test_record_list_resolve(client):
    # No mistakes yet.
    assert (await client.get("/api/mistakes/count")).json()["count"] == 0

    # Record one.
    res = await client.post("/api/mistakes/", json={
        "source": "mcq", "subject": "maths", "topic": "Arithmetic", "question": _q(),
    })
    assert res.status_code == 204
    assert (await client.get("/api/mistakes/count")).json()["count"] == 1

    # Recording the same question again is idempotent (upsert on question text).
    await client.post("/api/mistakes/", json={
        "source": "mcq", "subject": "maths", "topic": "Arithmetic", "question": _q(),
    })
    assert (await client.get("/api/mistakes/count")).json()["count"] == 1

    # It shows up in the deck, filtered by subject.
    listed = (await client.get("/api/mistakes/?subject=maths")).json()
    assert len(listed) == 1
    assert listed[0]["question"]["question"] == "What is 2+2?"
    assert (await client.get("/api/mistakes/?subject=physics")).json() == []

    # Getting it right removes it.
    res = await client.post("/api/mistakes/resolve", json={"front": "What is 2+2?"})
    assert res.json()["resolved"] is True
    assert (await client.get("/api/mistakes/count")).json()["count"] == 0

    # Resolving an unknown card is a no-op.
    assert (await client.post("/api/mistakes/resolve", json={"front": "nope"})).json()["resolved"] is False


@pytest.mark.asyncio
async def test_malformed_question_ignored(client):
    res = await client.post("/api/mistakes/", json={"source": "mcq", "question": {"question": "   "}})
    assert res.status_code == 204
    assert (await client.get("/api/mistakes/count")).json()["count"] == 0
