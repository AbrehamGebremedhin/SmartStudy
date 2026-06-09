"""
Input sanitization and prompt-injection detection for all AI-touching endpoints.
"""

import base64
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Known injection / jailbreak patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    # Role-hijacking phrases
    r"ignore\s+(all\s+)?(previous|prior|above|earlier|your)\s+(instructions?|rules?|guidelines?|constraints?|prompts?|context)",
    r"disregard\s+(all\s+)?(previous|prior|above|earlier|your)\s+(instructions?|rules?|guidelines?|constraints?)",
    r"forget\s+(everything|all|your|previous|prior|the\s+above)",
    r"you\s+are\s+now\s+(a|an|the|going\s+to\s+be)",
    r"act\s+as\s+(if\s+you\s+(are|were)|a|an|the)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"your\s+new\s+(role|persona|identity|instructions?|task|job|purpose)",
    r"from\s+now\s+on\s+you\s+(are|will|must|should)",
    r"switch\s+(to|into)\s+(a\s+)?different\s+(mode|role|persona)",
    r"new\s+persona",
    r"\bDAN\b",
    r"do\s+anything\s+now",
    r"jailbreak",
    # Instruction injection via common prompt delimiters
    r"<\s*/?system\s*>",
    r"\[INST\]",
    r"\[\/INST\]",
    r"<<SYS>>",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"<\|system\|>",
    # "Override" commands
    r"override\s+(your\s+)?(safety|guidelines?|instructions?|rules?|constraints?|filters?)",
    r"bypass\s+(your\s+)?(safety|guidelines?|instructions?|rules?|filters?|restrictions?)",
    r"disable\s+(your\s+)?(safety|guidelines?|filters?|restrictions?)",
    # Explicit "do not follow" attacks
    r"do\s+not\s+follow\s+(your|the)\s+(instructions?|guidelines?|rules?)",
    r"you\s+must\s+not\s+(follow|adhere\s+to)\s+(your|the)\s+(instructions?|guidelines?|rules?)",
    # System prompt extraction attempts
    r"(print|repeat|show|reveal|tell\s+me|output|write\s+out)\s+(your\s+)?(system\s+prompt|initial\s+instructions?|original\s+instructions?|full\s+prompt)",
    r"what\s+(are|were)\s+your\s+(exact\s+)?(system\s+)?instructions?",
    # Token/context smuggling tricks
    r"###\s*(instruction|system|human|assistant|prompt)",
    r"-{3,}\s*(instruction|system|human|assistant)",
    r"```\s*(instruction|system|human|assistant)",
    # Additional jailbreak variants
    r"(respond|reply|answer|output)\s+only\s+in\s+(your\s+)?(true|real|original|unrestricted)",
    r"you\s+(have\s+)?no\s+(restrictions?|limitations?|guidelines?|rules?)",
    r"(evil|opposite|shadow|dark|unrestricted|uncensored)\s+(mode|version|self|ai|gpt|llm)",
    r"hypothetically\s+speaking.{0,50}(ignore|bypass|pretend)",
    r"(translate|decode|convert)\s+the\s+following.{0,30}(instruction|command)",
]]

# Unicode direction-override / invisible characters that can hide injected text
_BAD_UNICODE_CHARS = frozenset([
    "​",  # zero-width space
    "‌",  # zero-width non-joiner
    "‍",  # zero-width joiner
    "‪",  # left-to-right embedding
    "‫",  # right-to-left embedding
    "‬",  # pop directional formatting
    "‭",  # left-to-right override
    "‮",  # right-to-left override
    "⁦",  # left-to-right isolate
    "⁧",  # right-to-left isolate
    "⁨",  # first strong isolate
    "⁩",  # pop directional isolate
    "⁪",  # inhibit symmetric swapping
    "⁫",  # activate symmetric swapping
    "﻿",  # BOM / zero-width no-break space
])


@dataclass(frozen=True)
class SanitizeResult:
    cleaned: str
    injection_detected: bool
    pattern_matched: str | None


# Leetspeak → ASCII normalization table used only for pattern-scan pass
_LEET_TABLE = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "@": "a", "$": "s", "!": "i", "|": "i",
})

# Cyrillic homoglyphs that look like Latin letters
_HOMOGLYPH_TABLE = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ѕ": "s", "ј": "j",
})


def _normalize_for_scan(text: str) -> str:
    """Produce a normalized copy for pattern scanning only (not returned to callers)."""
    # NFKD collapses accented/styled Unicode variants to ASCII base characters
    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.translate(_LEET_TABLE)
    normalized = normalized.lower()
    # Collapse inserted spaces/dots/dashes within words (e.g. "i g n o r e" → "ignore")
    normalized = re.sub(r"(?<=[a-z])[\s.\-_]+(?=[a-z])", "", normalized)
    return normalized


def _check_base64_payload(text: str) -> bool:
    """Return True if any base64-looking chunk in text decodes to injection keywords."""
    _DANGER_KEYWORDS = [b"ignore", b"bypass", b"jailbreak", b"system prompt", b"act as"]
    for chunk in re.findall(r"[A-Za-z0-9+/]{20,}={0,2}", text):
        try:
            decoded = base64.b64decode(chunk + "==").lower()
            if any(kw in decoded for kw in _DANGER_KEYWORDS):
                return True
        except Exception:
            pass
    return False


def sanitize(text: str) -> SanitizeResult:
    """
    Strip dangerous Unicode characters, normalize whitespace, then check for
    known prompt-injection patterns — including leetspeak, homoglyph, and
    base64-encoded bypass attempts.

    Returns a SanitizeResult.  Callers should check `injection_detected` and
    reject the request if True — never surface `pattern_matched` to the client.
    """
    # 1. Remove invisible / direction-override characters
    cleaned = "".join(ch for ch in text if ch not in _BAD_UNICODE_CHARS)

    # 2. Translate Cyrillic homoglyphs before NFC so they survive normalization
    cleaned = cleaned.translate(_HOMOGLYPH_TABLE)

    # 3. NFC-normalize to collapse lookalike characters
    cleaned = unicodedata.normalize("NFC", cleaned)

    # 4. Collapse runs of whitespace (keeps single spaces/newlines)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    # 5. Check for base64-encoded injection payloads
    if _check_base64_payload(cleaned):
        return SanitizeResult(
            cleaned=cleaned,
            injection_detected=True,
            pattern_matched="base64_encoded_payload",
        )

    # 6. Scan the raw cleaned text AND a leetspeak-normalized version
    scan_targets = [cleaned, _normalize_for_scan(cleaned)]
    for scan_text in scan_targets:
        for pattern in _INJECTION_PATTERNS:
            match = pattern.search(scan_text)
            if match:
                return SanitizeResult(
                    cleaned=cleaned,
                    injection_detected=True,
                    pattern_matched=pattern.pattern,
                )

    return SanitizeResult(cleaned=cleaned, injection_detected=False, pattern_matched=None)


def sanitize_dict(data: dict[str, Any], string_fields: list[str]) -> tuple[dict[str, Any], bool, str | None]:
    """
    Sanitize specific string fields in a dict in-place.

    Returns (mutated_dict, injection_detected, pattern_matched).
    Stops at first injection hit.
    """
    for field in string_fields:
        value = data.get(field)
        if not isinstance(value, str):
            continue
        result = sanitize(value)
        if result.injection_detected:
            return data, True, result.pattern_matched
        data[field] = result.cleaned
    return data, False, None
