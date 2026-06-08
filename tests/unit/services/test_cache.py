"""
Unit tests for app/services/cache.py.

No I/O, no DB, no LLM — pure logic.
"""
import pytest
from app.services.cache import _parse_token_usage, compute_request_hash


@pytest.mark.unit
class TestComputeRequestHash:
    def test_same_params_same_hash(self):
        params = {"subject": "physics", "grade": 11, "unit": "1", "num_questions": 5, "difficulty": "medium"}
        assert compute_request_hash(params) == compute_request_hash(params)

    def test_different_params_different_hash(self):
        p1 = {"subject": "physics", "grade": 11}
        p2 = {"subject": "chemistry", "grade": 11}
        assert compute_request_hash(p1) != compute_request_hash(p2)

    def test_key_order_does_not_matter(self):
        p1 = {"subject": "physics", "grade": 11}
        p2 = {"grade": 11, "subject": "physics"}
        assert compute_request_hash(p1) == compute_request_hash(p2)

    def test_different_grade_different_hash(self):
        p1 = {"subject": "physics", "grade": 11}
        p2 = {"subject": "physics", "grade": 12}
        assert compute_request_hash(p1) != compute_request_hash(p2)

    def test_none_value_included_in_hash(self):
        p1 = {"subject": "physics", "unit": None}
        p2 = {"subject": "physics", "unit": "1"}
        assert compute_request_hash(p1) != compute_request_hash(p2)

    def test_hash_is_64_char_hex_string(self):
        result = compute_request_hash({"key": "value"})
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_is_deterministic_across_calls(self):
        params = {"subject": "biology", "grade": 9, "unit": "2", "num_questions": 10}
        hashes = [compute_request_hash(params) for _ in range(5)]
        assert len(set(hashes)) == 1


@pytest.mark.unit
class TestParseTokenUsage:
    def test_full_string_parses_correctly(self):
        usage = "Input: 1,500 | Output: 3,200 | $0.0015"
        inp, out, cost = _parse_token_usage(usage)
        assert inp == 1500
        assert out == 3200
        assert abs(cost - 0.0015) < 1e-9

    def test_simple_string_no_commas(self):
        inp, out, cost = _parse_token_usage("Input: 500 | Output: 1200 | $0.0004")
        assert inp == 500
        assert out == 1200

    def test_none_returns_zeros(self):
        assert _parse_token_usage(None) == (0, 0, 0.0)

    def test_empty_string_returns_zeros(self):
        assert _parse_token_usage("") == (0, 0, 0.0)

    def test_missing_cost_returns_zero_cost(self):
        inp, out, cost = _parse_token_usage("Input: 100 | Output: 200")
        assert inp == 100
        assert out == 200
        assert cost == 0.0

    def test_missing_output_returns_zero_output(self):
        inp, out, cost = _parse_token_usage("Input: 100 | $0.001")
        assert inp == 100
        assert out == 0

    def test_large_token_counts_with_commas(self):
        inp, out, _ = _parse_token_usage("Input: 100,000 | Output: 50,000 | $0.05")
        assert inp == 100_000
        assert out == 50_000
