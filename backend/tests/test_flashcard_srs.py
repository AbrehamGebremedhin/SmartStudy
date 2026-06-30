"""Leitner spaced-repetition: pure box logic + /flashcards review/due endpoints."""
import pytest

from app.services import srs


def test_box_progression():
    assert srs.next_box(1, True) == 2
    assert srs.next_box(5, True) == 5      # caps
    assert srs.next_box(4, False) == 1     # forgotten resets
    assert srs.card_key(" Foo? ") == srs.card_key("foo?")  # normalized


pytestmark_async = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_review_then_due(client):
    card = {"front": "What is osmosis?", "back": "Water moving across a membrane",
            "topic": "Transport", "subject": "biology", "known": False}

    # "still learning" -> box 1, due in 1 day -> shows up as due immediately? No:
    # due_at is now+1day, so NOT due yet. Verify it's stored at box 1.
    res = await client.post("/api/flashcards/review", json=card)
    assert res.status_code == 200
    assert res.json()["box"] == 1

    # Knowing it advances the box.
    res2 = await client.post("/api/flashcards/review", json={**card, "known": True})
    assert res2.json()["box"] == 2

    # Nothing is due yet (all intervals are >= 1 day in the future).
    due = await client.get("/api/flashcards/due?subject=biology")
    assert due.status_code == 200
    assert due.json() == []
