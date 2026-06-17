from app.utils.enrich_questions import to_letter

OPTS = [
    {"letter": "A", "text": "current is zero"},
    {"letter": "B", "text": "potential drop equals emf"},
    {"letter": "C", "text": "charge entering equals charge leaving"},
    {"letter": "D", "text": "sum of voltage drops"},
]


def test_to_letter():
    assert to_letter("C", OPTS) == "C"                                   # plain letter (Gemini)
    assert to_letter("charge entering equals charge leaving", OPTS) == "C"  # exact text (gemma4)
    assert to_letter("charge entering the junction equals the charge leaving", OPTS) == "C"  # superset
    assert to_letter("nonsense xyz", OPTS) is None
    assert to_letter(None, OPTS) is None
