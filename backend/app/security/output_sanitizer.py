"""
Sanitize LLM output before returning to API clients.

Strips HTML tags and script content from string values to provide
defense-in-depth against prompt-injection-induced XSS.
React already escapes by default, but this protects non-React consumers
and any future dangerouslySetInnerHTML usage.
"""

import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_EVENT_ATTR_RE = re.compile(r'\bon\w+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)

# Fields that are structural/enum values — skip sanitization
_SAFE_KEYS = frozenset({
    "type", "difficulty", "subject", "grade", "error", "unit",
    "role", "model", "was_cache_hit", "session_id", "token_usage",
})

_MAX_STRING_LENGTH = 50_000


def sanitize_string(value: str) -> str:
    """Strip HTML/script tags from a string."""
    value = _SCRIPT_RE.sub("", value)
    value = _EVENT_ATTR_RE.sub("", value)
    value = _HTML_TAG_RE.sub("", value)
    if len(value) > _MAX_STRING_LENGTH:
        value = value[:_MAX_STRING_LENGTH]
    return value


def sanitize_output(data: object, _key: str | None = None) -> object:
    """Recursively sanitize all string values in a dict/list structure."""
    if isinstance(data, str):
        if _key in _SAFE_KEYS:
            return data
        return sanitize_string(data)
    if isinstance(data, dict):
        return {k: sanitize_output(v, _key=k) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_output(item, _key=_key) for item in data]
    return data
