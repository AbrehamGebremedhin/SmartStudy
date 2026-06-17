"""
GeminiKeyPool — rotation across several Gemini API keys for the offline
exam-question enrichment job.

Free-tier quota is enforced PER GOOGLE CLOUD PROJECT, not per key, so this only
multiplies throughput when every key comes from a distinct project. Each key
gets its own client and independent throttle state:

  * per-minute 429  -> short cooldown (honours the API's retryDelay when present)
  * daily quota     -> mark the key exhausted until the next 08:00 UTC reset

When all keys are momentarily cooling the pool waits for the soonest one; when
all keys are daily-exhausted it sleeps until the reset so a long run survives the
quota boundary unattended.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from google import genai
from google.genai import errors, types

logger = logging.getLogger(__name__)

# Default to the model that is reliably present on the free tier and multimodal.
# Override to a newer flash model if every key's project has it enabled.
DEFAULT_MODEL = "gemini-2.5-flash"

REQUEST_TIMEOUT = 120.0      # hard wall on a single Gemini call (s) — guards against hangs
PER_MINUTE_COOLDOWN = 65.0   # fallback when the API gives no retryDelay
_RETRY_DELAY_RE = re.compile(r"retry.?delay[\"']?\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)", re.I)


def _next_utc_reset_epoch() -> float:
    """Epoch seconds of the next 08:00 UTC (== 00:00 PT free-tier daily reset)."""
    now = datetime.now(timezone.utc)
    reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= reset:
        reset += timedelta(days=1)
    return reset.timestamp()


def _parse_retry_delay(message: str) -> float | None:
    m = _RETRY_DELAY_RE.search(message or "")
    return float(m.group(1)) if m else None


def _is_daily_quota(message: str) -> bool:
    msg = (message or "").lower()
    return "perday" in msg or "per day" in msg or "daily" in msg


class _KeyState:
    __slots__ = ("idx", "client", "cooling_until", "exhausted_until", "calls", "errors")

    def __init__(self, idx: int, api_key: str):
        self.idx = idx
        self.client = genai.Client(api_key=api_key)
        self.cooling_until = 0.0      # per-minute cooldown (epoch)
        self.exhausted_until = 0.0    # daily-quota wall (epoch)
        self.calls = 0
        self.errors = 0

    def available_at(self) -> float:
        return max(self.cooling_until, self.exhausted_until)

    def status(self, now: float) -> str:
        if self.exhausted_until > now:
            return "exhausted"
        if self.cooling_until > now:
            return "cooling"
        return "active"


class GeminiKeyPool:
    def __init__(self, api_keys: list[str], model: str = DEFAULT_MODEL):
        if not api_keys:
            raise ValueError("GeminiKeyPool requires at least one API key")
        self.model = model
        self.states = [_KeyState(i, k) for i, k in enumerate(api_keys)]
        self._rr = 0
        self._lock = asyncio.Lock()
        logger.info("GeminiKeyPool: %d key(s), model=%s", len(self.states), model)

    # -- key selection ---------------------------------------------------------

    async def _acquire(self) -> _KeyState:
        """Return the next available key, sleeping (and logging) if none are ready."""
        while True:
            async with self._lock:
                now = time.time()
                n = len(self.states)
                for step in range(n):
                    s = self.states[(self._rr + step) % n]
                    if s.available_at() <= now:
                        self._rr = (self._rr + step + 1) % n
                        return s
                soonest = min(s.available_at() for s in self.states)
            wait = max(1.0, soonest - time.time())
            if all(s.exhausted_until > time.time() for s in self.states):
                resume = datetime.fromtimestamp(soonest, timezone.utc).isoformat()
                logger.warning("All keys daily-exhausted; sleeping %.0fs until reset (%s)", wait, resume)
            else:
                logger.info("All keys cooling; waiting %.0fs", wait)
            await asyncio.sleep(min(wait, 300))

    # -- generation ------------------------------------------------------------

    async def generate(
        self,
        contents,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        response_mime_type: str = "application/json",
        max_attempts: int = 8,
    ) -> str:
        """Generate content with key rotation + retry. Returns the response text."""
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type=response_mime_type,
            # Disable 2.5-flash "thinking" — it inflates latency (batches exceed the
            # request timeout) and token usage; not needed for this structured task.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        attempt = 0
        while True:
            attempt += 1
            state = await self._acquire()
            try:
                resp = await asyncio.wait_for(
                    state.client.aio.models.generate_content(
                        model=self.model, contents=contents, config=config,
                    ),
                    timeout=REQUEST_TIMEOUT,
                )
                state.calls += 1
                return resp.text
            except asyncio.TimeoutError:
                state.errors += 1
                if attempt >= max_attempts:
                    raise
                logger.warning("Key #%d timed out after %.0fs; retrying (attempt %d).",
                               state.idx, REQUEST_TIMEOUT, attempt)
                continue
            except errors.APIError as e:
                state.errors += 1
                code = getattr(e, "code", None)
                msg = getattr(e, "message", str(e))
                if code == 429:
                    now = time.time()
                    if _is_daily_quota(msg):
                        state.exhausted_until = _next_utc_reset_epoch()
                        logger.warning("Key #%d daily-exhausted.", state.idx)
                    else:
                        delay = _parse_retry_delay(msg) or PER_MINUTE_COOLDOWN
                        state.cooling_until = now + delay
                        logger.info("Key #%d rate-limited; cooling %.0fs.", state.idx, delay)
                    continue  # retry on another key without consuming an attempt budget
                if code in (500, 502, 503, 504):
                    if attempt >= max_attempts:
                        raise
                    backoff = min(2 ** attempt, 60)
                    logger.warning("Key #%d server error %s; backoff %ss (attempt %d).",
                                   state.idx, code, backoff, attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise  # non-retryable (400 bad request, invalid model, etc.)
            except Exception as e:  # noqa: BLE001 — network/SSL/getaddrinfo blips: retry
                state.errors += 1
                if attempt >= max_attempts:
                    raise
                backoff = min(2 ** attempt, 60)
                logger.warning("Key #%d connection error (%s); backoff %ss (attempt %d).",
                               state.idx, type(e).__name__, backoff, attempt)
                await asyncio.sleep(backoff)
                continue

    # -- introspection ---------------------------------------------------------

    def status_line(self) -> str:
        now = time.time()
        parts = [f"P{s.idx + 1}:{s.status(now)}({s.calls})" for s in self.states]
        return " ".join(parts)

    def total_calls(self) -> int:
        return sum(s.calls for s in self.states)
