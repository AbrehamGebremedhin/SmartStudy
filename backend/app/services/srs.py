"""Leitner-box spaced repetition. Pure logic, no DB.

Ratings are binary (the flashcard UI only offers "knew it" / "still learning"),
so a Leitner box ladder fits exactly — SM-2's ease factors would be dead math
on a two-valued grade. A card climbs one box when known, drops to box 1 when not;
the box maps to how many days until it's due again.

ponytail: fixed 5-box ladder. If we ever collect graded confidence (1–5) instead
of binary, swap this for SM-2.
"""
import hashlib
from datetime import datetime, timedelta, timezone

# box -> days until next review
BOX_INTERVALS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 15}
MAX_BOX = 5


def card_key(front: str) -> str:
    """Stable id for a card from its question text (cards carry no id)."""
    return hashlib.sha256(front.strip().lower().encode()).hexdigest()


def next_box(current_box: int, known: bool) -> int:
    if not known:
        return 1
    return min(current_box + 1, MAX_BOX)


def due_at(box: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(days=BOX_INTERVALS[box])


def _demo() -> None:
    assert card_key("  What is 2+2? ") == card_key("what is 2+2?")
    assert next_box(1, True) == 2
    assert next_box(5, True) == 5  # caps at MAX_BOX
    assert next_box(3, False) == 1  # forgotten -> back to box 1
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert due_at(1, base) == base + timedelta(days=1)
    assert due_at(5, base) == base + timedelta(days=15)
    print("srs demo OK")


if __name__ == "__main__":
    _demo()
