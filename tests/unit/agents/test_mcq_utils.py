"""
Unit tests for app/agents/mcq_utils.py.

No I/O, no DB, no LLM — pure logic.
"""
import sys
from pathlib import Path

# mcq_utils.py uses bare imports resolved from app/agents
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "agents"))

import pytest
from unittest.mock import patch
from mcq_utils import (
    SELF_REF_OPTION,
    TEST_PREP_ARTIFACT,
    is_test_prep_artifact,
    redistribute_answer_positions,
    swap_letter_refs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_question(correct: str = "A", topic: str = "Physics") -> dict:
    letters = ["A", "B", "C", "D"]
    # Use plain numeric values to avoid accidentally triggering SELF_REF_OPTION
    # (words like "Options", "Both", "All" in the option text would be mis-detected)
    contents = ["2 m/s^2", "5 m/s^2", "10 m/s^2", "20 m/s^2"]
    options = [f"{l}) {contents[i]}" for i, l in enumerate(letters)]
    return {
        "topic": topic,
        "question": f"What is the acceleration? (correct={correct})",
        "options": options,
        "correct_answer": correct,
        "passage": None,
        "workout_steps": [],
        "correct_explanations": [f"Answer {correct} is correct by Newton's second law"],
        "incorrect_explanations": {l: f"Value {l} is incorrect" for l in letters if l != correct},
    }


def _make_questions(n: int, all_correct: str = "A") -> list[dict]:
    return [_make_question(correct=all_correct) for _ in range(n)]


# ---------------------------------------------------------------------------
# is_test_prep_artifact
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsTestPrepArtifact:
    def test_sat_with_artifact_returns_true(self):
        assert is_test_prep_artifact("sat", "What is the scoring rubric for this section?")

    def test_english_with_artifact_returns_true(self):
        assert is_test_prep_artifact("english", "According to the passage, the author argues...")

    def test_non_sat_subject_always_false(self):
        assert not is_test_prep_artifact("physics", "The answer is in the passage")

    def test_sat_clean_text_returns_false(self):
        assert not is_test_prep_artifact("sat", "What is the synonym of 'haggard'?")

    def test_empty_text_returns_false(self):
        assert not is_test_prep_artifact("sat", "")

    def test_multiple_texts_any_match(self):
        assert is_test_prep_artifact("sat", "clean question", "scoring rubric guide")

    def test_passage_evidence_triggers(self):
        assert is_test_prep_artifact("sat", "Use passage evidence to support your answer")

    def test_case_insensitive(self):
        assert is_test_prep_artifact("english", "ACCORDING TO THE PASSAGE")


# ---------------------------------------------------------------------------
# swap_letter_refs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSwapLetterRefs:
    def test_swaps_answer_is_pattern(self):
        text = "The answer is A because it is correct."
        result = swap_letter_refs(text, "A", "C")
        assert "answer is C" in result

    def test_swaps_option_reference(self):
        text = "Option A is incorrect."
        result = swap_letter_refs(text, "A", "B")
        assert "Option B" in result

    def test_no_change_when_same_letters(self):
        text = "The answer is A."
        assert swap_letter_refs(text, "A", "A") == text

    def test_no_change_when_no_reference(self):
        text = "This explanation contains no letter reference."
        assert swap_letter_refs(text, "A", "C") == text

    def test_empty_string(self):
        assert swap_letter_refs("", "A", "B") == ""

    def test_thus_pattern(self):
        text = "Thus, A is the correct choice."
        result = swap_letter_refs(text, "A", "D")
        assert "D" in result

    def test_both_letters_swapped_bidirectionally(self):
        text = "Option A is right and option B is wrong."
        result = swap_letter_refs(text, "A", "B")
        # After swap: A→B, B→A
        assert "Option B is right" in result or "option A is wrong" in result


# ---------------------------------------------------------------------------
# SELF_REF_OPTION
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSelfRefOption:
    @pytest.mark.parametrize("text", [
        "Both A and B are correct",
        "All of the above",
        "None of the above",
        "Options A and B",
        "Either A or B",
    ])
    def test_detects_self_referencing_option(self, text):
        assert SELF_REF_OPTION.search(text)

    @pytest.mark.parametrize("text", [
        "Newton's second law",
        "The velocity increases",
        "Answer choice is acceleration",
    ])
    def test_clean_option_not_matched(self, text):
        assert not SELF_REF_OPTION.search(text)


# ---------------------------------------------------------------------------
# redistribute_answer_positions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedistributeAnswerPositions:
    def test_empty_list_returns_empty(self):
        assert redistribute_answer_positions([]) == []

    def test_single_question_returned(self):
        q = _make_question("A")
        result = redistribute_answer_positions([q])
        assert len(result) == 1
        # The option labelled with the correct_answer letter must carry the original A content
        correct_letter = result[0]["correct_answer"]
        options = result[0]["options"]
        winning_option = next(o for o in options if o.startswith(f"{correct_letter})"))
        assert "2 m/s^2" in winning_option  # original A content (index 0 → "2 m/s^2")

    def test_correctness_preserved_after_redistribution(self):
        questions = _make_questions(8, all_correct="A")
        result = redistribute_answer_positions(questions)
        for q in result:
            correct_letter = q["correct_answer"]
            opts = {o[0]: o[3:] for o in q["options"]}
            # The option marked correct must contain the original A content ("2 m/s^2")
            assert "2 m/s^2" in opts[correct_letter]

    def test_distribution_spreads_across_abcd(self):
        import random

        questions = _make_questions(40, all_correct="A")
        # Force a deterministic shuffle so the test is not probabilistic
        with patch("mcq_utils.random.shuffle", side_effect=lambda lst: lst.sort()):
            result = redistribute_answer_positions(questions)
        counts = {"A": 0, "B": 0, "C": 0, "D": 0}
        for q in result:
            counts[q["correct_answer"]] += 1
        # With 40 questions and 4 letters, each appears exactly 10 times
        for letter, count in counts.items():
            assert count == 10, f"Expected 10 for {letter}, got {count}"

    def test_self_ref_options_skipped(self):
        q = _make_question("A")
        q["options"][1] = "B) All of the above"  # self-referencing
        result = redistribute_answer_positions([q])
        # Question should pass through unchanged when self-ref option found
        assert result[0]["correct_answer"] == "A"

    def test_malformed_options_skipped(self):
        q = _make_question("A")
        q["options"] = ["malformed", "also bad", "no letter prefix", "same"]
        result = redistribute_answer_positions([q])
        assert result[0]["correct_answer"] == "A"

    def test_incorrect_explanations_rekeyed(self):
        q = _make_question("A")
        result = redistribute_answer_positions([q])
        r = result[0]
        correct = r["correct_answer"]
        all_keys = set(r["incorrect_explanations"].keys())
        expected_keys = {"A", "B", "C", "D"} - {correct}
        assert all_keys == expected_keys
