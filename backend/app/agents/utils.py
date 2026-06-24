import asyncio
import functools
import json
import logging
import time
from typing import Any, Dict

from langchain_core.documents import Document


def format_docs(context) -> str:
    if isinstance(context, list):
        return "\n\n".join(
            doc.page_content if isinstance(doc, Document) else str(doc)
            for doc in context
        )
    return str(context)


def retry_on_none(max_retries=3):
    """Retry a function up to max_retries times if it returns None, with exponential back-off."""
    def decorator_retry(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                for attempt in range(max_retries):
                    result = await func(*args, **kwargs)
                    if result is not None:
                        return result
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                raise ValueError(f"Failed to get a valid response after {max_retries} attempts")
            return async_wrapper
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                for attempt in range(max_retries):
                    result = func(*args, **kwargs)
                    if result is not None:
                        return result
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                raise ValueError(f"Failed to get a valid response after {max_retries} attempts")
            return wrapper
    return decorator_retry


def clean_unicode(text: str) -> str:
    """Replace Unicode math/formatting characters with ASCII equivalents."""
    if not isinstance(text, str):
        return text

    replacements = {
        # Superscript numbers
        '²': '^2', '³': '^3', '⁰': '^0', '¹': '^1',
        '⁴': '^4', '⁵': '^5', '⁶': '^6', '⁷': '^7',
        '⁸': '^8', '⁹': '^9',
        # Superscript operators
        '⁺': '^+', '⁻': '^-', '⁼': '^=',
        '⁽': '^(', '⁾': '^)',
        # Mathematical symbols
        '–': '-', '—': '--', '−': '-',
        '×': 'x', '÷': '/', '±': '+-',
        '√': 'sqrt', '∞': 'inf', '≈': '~=',
        '≠': '!=', '≤': '<=', '≥': '>=',
        # Greek letters
        'α': 'alpha', 'β': 'beta', 'γ': 'gamma',
        'π': 'pi', 'μ': 'mu',
        # Quotes and formatting
        '‘': "'", '’': "'", '“': '"', '”': '"',
        '•': '*', '\n': '\\n',
    }

    result = text
    for unicode_char, replacement in replacements.items():
        result = result.replace(unicode_char, replacement)
    return result


def _escape_ctrl_in_strings(text: str) -> str:
    """Escape raw newlines/tabs/CRs that sit *inside* JSON string literals.

    A blanket regex would also escape the structural whitespace between tokens
    (e.g. the newline after `{`), turning valid JSON into `{\\n"key"` — two stray
    chars where a key is expected. So track quote state and only repair within
    strings, respecting backslash escapes.
    """
    out: list[str] = []
    in_str = False
    escaped = False
    for ch in text:
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            continue
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == '\\':
            out.append(ch)
            escaped = True
        elif ch == '"':
            out.append(ch)
            in_str = False
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        else:
            out.append(ch)
    return ''.join(out)


def _try_parse(text: str) -> Any:
    """Attempt json.loads, then retry with control chars escaped inside strings."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    return json.loads(_escape_ctrl_in_strings(text))  # let this raise if still broken


def parse_llm_response(response: str, logger: logging.Logger = None) -> Dict[str, Any]:
    """Parse a raw LLM response string into a structured dict."""
    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        start_idx = cleaned.find('{')
        end_idx = cleaned.rfind('}') + 1
        if start_idx != -1 and end_idx > start_idx:
            cleaned = cleaned[start_idx:end_idx]

        parsed = _try_parse(cleaned)

        if isinstance(parsed, dict):
            if "response" in parsed:
                if isinstance(parsed["response"], dict):
                    parsed["response"]["response"] = clean_unicode(parsed["response"]["response"])
                else:
                    parsed["response"] = clean_unicode(str(parsed["response"]))

        # Chat / context-refinement responses
        if "response" in parsed or "key_concepts" in parsed:
            return parsed

        # MCQ / flashcard responses
        if "questions" in parsed or "flashcards" in parsed:
            return parsed

        # Notes core response (title/overview/key_concepts/theoretical_framework/connections)
        # Notes applied response (formulas/worked_examples/practice_problems/real_world_applications/review_questions)
        _notes_keys = {"title", "overview", "learning_objectives", "theoretical_framework",
                       "connections", "formulas_and_equations", "worked_examples",
                       "practice_problems", "real_world_applications", "review_questions"}
        if parsed.keys() & _notes_keys:
            return parsed

        return {"error": "Invalid response format", "raw_response": cleaned}

    except json.JSONDecodeError as e:
        if logger:
            logger.error(f"Failed to parse JSON response: {e}")
        return {"error": f"Failed to parse response: {e}", "raw_response": response}
