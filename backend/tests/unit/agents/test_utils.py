"""
Unit tests for app/agents/utils.py.

No I/O, no DB, no LLM — pure logic.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app" / "agents"))

import pytest
from langchain_core.documents import Document

from utils import clean_unicode, format_docs, parse_llm_response, retry_on_none


# ---------------------------------------------------------------------------
# format_docs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatDocs:
    def test_empty_list(self):
        assert format_docs([]) == ""

    def test_single_document(self):
        doc = Document(page_content="Hello world")
        assert format_docs([doc]) == "Hello world"

    def test_multiple_documents_joined_with_double_newline(self):
        docs = [Document(page_content="First"), Document(page_content="Second")]
        result = format_docs(docs)
        assert result == "First\n\nSecond"

    def test_non_document_strings(self):
        result = format_docs(["chunk one", "chunk two"])
        assert result == "chunk one\n\nchunk two"

    def test_plain_string_passthrough(self):
        assert format_docs("plain string") == "plain string"


# ---------------------------------------------------------------------------
# clean_unicode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanUnicode:
    def test_superscript_numbers(self):
        assert clean_unicode("x²") == "x^2"
        assert clean_unicode("x³") == "x^3"

    def test_math_operators(self):
        assert clean_unicode("a × b") == "a x b"
        assert clean_unicode("a ÷ b") == "a / b"
        assert clean_unicode("a ≤ b") == "a <= b"
        assert clean_unicode("a ≥ b") == "a >= b"

    def test_minus_variants(self):
        assert clean_unicode("a – b") == "a - b"
        assert clean_unicode("a − b") == "a - b"

    def test_greek_letters(self):
        assert clean_unicode("π") == "pi"
        assert clean_unicode("α") == "alpha"

    def test_sqrt(self):
        assert clean_unicode("√x") == "sqrtx"

    def test_non_string_passthrough(self):
        assert clean_unicode(42) == 42  # type: ignore

    def test_no_change_on_ascii(self):
        text = "Simple ASCII string with no special chars."
        assert clean_unicode(text) == text


# ---------------------------------------------------------------------------
# parse_llm_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseLlmResponse:
    def test_plain_json_dict(self):
        result = parse_llm_response('{"questions": []}')
        assert result == {"questions": []}

    def test_fenced_json_block(self):
        result = parse_llm_response('```json\n{"questions": []}\n```')
        assert result == {"questions": []}

    def test_fenced_block_without_language_tag(self):
        result = parse_llm_response('```\n{"flashcards": []}\n```')
        assert result == {"flashcards": []}

    def test_json_with_surrounding_text(self):
        result = parse_llm_response('Here is the result:\n{"questions": [1, 2]}')
        assert result == {"questions": [1, 2]}

    def test_malformed_json_returns_error(self):
        result = parse_llm_response("not json at all")
        assert "error" in result

    def test_response_key_preserved(self):
        raw = '{"response": "Hello world", "key_concepts": ["a"]}'
        result = parse_llm_response(raw)
        assert result["response"] == "Hello world"

    def test_nested_response_dict_cleaned(self):
        raw = '{"response": {"response": "Hello²", "key_concepts": []}}'
        result = parse_llm_response(raw)
        # clean_unicode replaces ² with ^2
        assert "^2" in result["response"]["response"]

    def test_missing_questions_and_flashcards_returns_error(self):
        result = parse_llm_response('{"unrelated_key": "value"}')
        assert "error" in result

    def test_bare_newlines_in_json_repaired(self):
        # A JSON string with unescaped newlines inside a value
        raw = '{"questions": "line1\nline2"}'
        result = parse_llm_response(raw)
        assert "questions" in result

    def test_structural_newlines_not_corrupted_by_repair(self):
        # The load-test failure: pretty-printed JSON (structural newlines) with a
        # bare newline inside ONE value. The repair must escape only the in-string
        # newline, not the structural ones — otherwise `{\n` becomes a stray token
        # and parsing dies with "Expecting property name ... char 1".
        raw = '{\n  "questions": "line1\nline2",\n  "difficulty": "hard"\n}'
        result = parse_llm_response(raw)
        assert result["difficulty"] == "hard"
        assert result["questions"] == "line1\nline2"   # in-string newline preserved

    def test_bare_tab_inside_value_repaired(self):
        raw = '{"questions": "a\tb"}'
        result = parse_llm_response(raw)
        assert result["questions"] == "a\tb"


# ---------------------------------------------------------------------------
# retry_on_none
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetryOnNone:
    def test_sync_succeeds_first_try(self):
        calls = []

        @retry_on_none(max_retries=3)
        def fn():
            calls.append(1)
            return "ok"

        result = fn()
        assert result == "ok"
        assert len(calls) == 1

    def test_sync_retries_on_none(self):
        calls = []

        @retry_on_none(max_retries=3)
        def fn():
            calls.append(1)
            return None if len(calls) < 2 else "done"

        result = fn()
        assert result == "done"
        assert len(calls) == 2

    def test_sync_raises_after_max_retries(self):
        @retry_on_none(max_retries=2)
        def fn():
            return None

        with pytest.raises(ValueError, match="Failed to get a valid response"):
            fn()

    async def test_async_succeeds_first_try(self):
        @retry_on_none(max_retries=3)
        async def fn():
            return "ok"

        result = await fn()
        assert result == "ok"

    async def test_async_retries_on_none(self):
        calls = []

        @retry_on_none(max_retries=3)
        async def fn():
            calls.append(1)
            return None if len(calls) < 2 else "done"

        result = await fn()
        assert result == "done"

    async def test_async_raises_after_max_retries(self):
        @retry_on_none(max_retries=2)
        async def fn():
            return None

        with pytest.raises(ValueError):
            await fn()
