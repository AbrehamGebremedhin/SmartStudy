import hashlib
import json
import re

# Fraction of items that are always freshly generated when a pool exists.
# The remainder (1 - POOL_FRESH_RATIO) is sampled from previous generations.
POOL_FRESH_RATIO = 0.65


def _parse_token_usage(token_usage_str: str | None) -> tuple[int, int, float]:
    """Extract (input_tokens, output_tokens, cost_usd) from agent token_usage string."""
    if not token_usage_str:
        return 0, 0, 0.0

    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0

    match = re.search(r"Input(?:\s+tokens)?:\s*([\d,]+)", token_usage_str, re.IGNORECASE)
    if match:
        input_tokens = int(match.group(1).replace(",", ""))

    match = re.search(r"Output(?:\s+tokens)?:\s*([\d,]+)", token_usage_str, re.IGNORECASE)
    if match:
        output_tokens = int(match.group(1).replace(",", ""))

    match = re.search(r"\$([\d.]+)", token_usage_str)
    if match:
        cost_usd = float(match.group(1))

    return input_tokens, output_tokens, cost_usd


def compute_request_hash(params: dict) -> str:
    """Produce a stable SHA-256 hash from a dict of request parameters."""
    normalized = json.dumps(params, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(normalized.encode()).hexdigest()
