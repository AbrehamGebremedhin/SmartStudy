"""
Unit tests for app/agents/subject_rules.py.

Pure logic — no I/O, no external calls.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "agents"))

import pytest
from subject_rules import (
    HUMANITIES_SUBJECTS,
    STEM_SUBJECTS,
    get_grounding_rule,
    get_mcq_subject_guidance,
    get_subject_focus,
    get_subject_rules,
    presentation_rules,
)

ALL_KNOWN_SUBJECTS = STEM_SUBJECTS + HUMANITIES_SUBJECTS + ["sat"]


@pytest.mark.unit
class TestGetSubjectRules:
    @pytest.mark.parametrize("subject", ALL_KNOWN_SUBJECTS)
    def test_known_subject_returns_non_empty_string(self, subject):
        rules = get_subject_rules(subject)
        assert isinstance(rules, str) and rules.strip()

    def test_unknown_subject_returns_general_fallback(self):
        rules = get_subject_rules("unknown_subject")
        assert "General format rules" in rules

    def test_biology_has_biochemical_accuracy_rules(self):
        rules = get_subject_rules("biology")
        assert "Electron transport chain" in rules or "BIOCHEMICAL" in rules

    @pytest.mark.parametrize("subject", ["maths", "physics", "chemistry"])
    def test_stem_has_workout_steps_guidance(self, subject):
        rules = get_subject_rules(subject)
        assert "workout steps" in rules.lower() or "step-by-step" in rules.lower()

    @pytest.mark.parametrize("subject", ["history", "civics", "geography"])
    def test_humanities_has_no_essay_guidance(self, subject):
        rules = get_subject_rules(subject)
        assert "essay" in rules.lower() or "factual" in rules.lower()

    def test_sat_has_verbal_and_quantitative_guidance(self):
        rules = get_subject_rules("sat")
        assert "verbal" in rules.lower() or "quantitative" in rules.lower()

    def test_case_insensitive_lookup(self):
        lower = get_subject_rules("biology")
        upper = get_subject_rules("BIOLOGY")
        assert lower == upper


@pytest.mark.unit
class TestGetMcqSubjectGuidance:
    def test_english_guidance_is_non_empty(self):
        guidance = get_mcq_subject_guidance("english")
        assert guidance.strip()

    def test_sat_guidance_is_non_empty(self):
        guidance = get_mcq_subject_guidance("sat")
        assert guidance.strip()

    def test_physics_returns_empty_string(self):
        assert get_mcq_subject_guidance("physics") == ""

    def test_english_mentions_reading_comprehension(self):
        guidance = get_mcq_subject_guidance("english")
        assert "reading" in guidance.lower()

    def test_sat_mentions_verbal_and_quantitative(self):
        guidance = get_mcq_subject_guidance("sat")
        assert "verbal" in guidance.lower()
        assert "quantitative" in guidance.lower()


@pytest.mark.unit
class TestGetGroundingRule:
    def test_sat_has_calibration_rule(self):
        rule = get_grounding_rule("sat")
        assert "calibrat" in rule.lower() or "context" in rule.lower()

    def test_english_has_calibration_rule(self):
        rule = get_grounding_rule("english")
        assert "calibrat" in rule.lower() or "context" in rule.lower()

    def test_physics_has_strict_context_rule(self):
        rule = get_grounding_rule("physics")
        assert "context" in rule.lower()
        assert "exclusively" in rule.lower() or "drawn" in rule.lower()

    def test_all_subjects_return_non_empty(self):
        for subject in ALL_KNOWN_SUBJECTS:
            assert get_grounding_rule(subject).strip()


@pytest.mark.unit
class TestGetSubjectFocus:
    def test_english_focus_mentions_reading(self):
        focus = get_subject_focus("english")
        assert "reading" in focus.lower()

    def test_sat_focus_mentions_verbal(self):
        focus = get_subject_focus("sat")
        assert "verbal" in focus.lower()

    def test_other_subjects_return_empty_string(self):
        assert get_subject_focus("physics") == ""
        assert get_subject_focus("history") == ""


@pytest.mark.unit
class TestPresentationRules:
    def test_returns_non_empty_string(self):
        rules = presentation_rules()
        assert isinstance(rules, str) and rules.strip()

    def test_no_meta_reference_rule_included(self):
        rules = presentation_rules()
        assert "context" in rules.lower() or "passage" in rules.lower()
