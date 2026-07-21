"""
Unit test for _apply_real_usage in app/services/generation.py.

Guards the contract that the real-usage string it writes is parseable by
cache._parse_token_usage (the routes rely on that round-trip to store token
columns). No I/O, no DB, no LLM.
"""
import pytest

from app.services.cache import _parse_token_usage
from app.services.generation import _apply_real_usage


class _FakeCB:
    """Mimics get_usage_metadata_callback's .usage_metadata: {model: UsageMetadata}."""
    def __init__(self, usage):
        self.usage_metadata = usage


@pytest.mark.unit
class TestApplyRealUsage:
    def test_aggregates_across_calls_and_roundtrips(self):
        cb = _FakeCB({
            "deepseek-v4-flash": {
                "input_tokens": 9000,
                "output_tokens": 2500,
                "input_token_details": {"cache_read": 6000},
            },
        })
        result = {"questions": []}
        _apply_real_usage(result, cb)

        inp, out, cost = _parse_token_usage(result["token_usage"])
        assert inp == 9000
        assert out == 2500
        assert cost > 0

    def test_no_usage_leaves_existing_value(self):
        cb = _FakeCB({})
        result = {"token_usage": "original"}
        _apply_real_usage(result, cb)
        assert result["token_usage"] == "original"
