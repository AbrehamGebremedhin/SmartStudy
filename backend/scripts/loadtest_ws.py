#!/usr/bin/env python3
"""End-to-end WS load test — REAL generations (this bills DeepSeek + runs Ollama).

Opens `--concurrency` real WebSocket connections to /api/ws/generate/mcq at once,
each asking for a fresh generation, and measures what an actual user feels:
time-to-result, success rate, and how badly latency degrades once the burst
exceeds the server's 8 worker slots (the overflow queues).

Unlike loadtest_queue.py this exercises the whole stack — auth, WS framing,
Ollama embedding retrieval, the DeepSeek call — so the numbers are real and so
is the cost. Keep --num-questions small and start with a low --concurrency.

Prereqs: the API server running (uvicorn), Ollama up, DEEPSEEK_API_KEY in .env.

Usage
-----
    # 5 users at once, 3 questions each:
    uv run python scripts/loadtest_ws.py --concurrency 5 --num-questions 3

    # push past the 8-worker cap to see queueing:
    uv run python scripts/loadtest_ws.py --concurrency 16 --num-questions 3
"""
import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ on path

from app.auth.tokens import create_app_token  # noqa: E402

PAYLOAD = {"subject": "physics", "grade": 11, "unit": "1", "difficulty": "medium"}


async def _one(url: str, payload: dict, timeout: float) -> dict:
    """Run one generation over a fresh WS; return its outcome + timing."""
    t0 = time.monotonic()
    stages = 0
    try:
        async with websockets.connect(url, max_size=None, open_timeout=15) as ws:
            await ws.send(_dumps(payload))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                msg = _loads(raw)
                kind = msg.get("type")
                if kind == "progress":
                    stages += 1
                elif kind == "result":
                    return {"ok": True, "secs": time.monotonic() - t0, "stages": stages,
                            "cache": msg["data"].get("was_cache_hit")}
                elif kind == "error":
                    return {"ok": False, "secs": time.monotonic() - t0,
                            "err": f"{msg.get('code')}: {msg.get('detail')}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "secs": time.monotonic() - t0, "err": f"{type(e).__name__}: {e}"}


def _url(host: str, i: int) -> str:
    # Distinct user per connection — concurrent logins of the *same* new google_id
    # race in get_or_create_user, which would mask the real capacity numbers.
    token = create_app_token({"sub": f"loadtest-{i}", "email": f"loadtest-{i}@example.com"})
    return f"{host}/api/ws/generate/mcq?token={token}"


async def main(host: str, concurrency: int, num_q: int, timeout: float) -> None:
    payload = {**PAYLOAD, "num_questions": num_q}
    print(f"Firing {concurrency} concurrent generations, {num_q} questions each -> {host}")
    print("(server caps concurrent generation at MAX_WORKERS=8; the rest queue)\n")

    t0 = time.monotonic()
    results = await asyncio.gather(*(_one(_url(host, i), payload, timeout) for i in range(concurrency)))
    wall = time.monotonic() - t0

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    lat = sorted(r["secs"] for r in ok)

    print(f"Wall time:     {wall:.1f}s for {concurrency} requests")
    print(f"Succeeded:     {len(ok)}/{concurrency}" + (f"   (cache hits: {sum(bool(r.get('cache')) for r in ok)})" if ok else ""))
    if lat:
        print(f"Time-to-result p50/p95/max: {_pct(lat, 50):.1f}s / {_pct(lat, 95):.1f}s / {lat[-1]:.1f}s")
        print(f"Throughput:    {len(ok) / wall:.2f} gen/s ({len(ok) / wall * 60:.0f}/min)")
    if bad:
        print(f"\nFailed {len(bad)}:")
        for r in bad[:10]:
            print(f"  {r['secs']:.1f}s  {r['err']}")


def _pct(values: list[float], p: int) -> float:
    if len(values) <= 1:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=100)[p - 1]


# orjson if present (server uses it), else stdlib — keep this script dependency-free.
try:
    import orjson

    def _dumps(o: dict) -> str: return orjson.dumps(o).decode()
    def _loads(s): return orjson.loads(s)
except ImportError:
    import json

    def _dumps(o: dict) -> str: return json.dumps(o)
    def _loads(s): return json.loads(s)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="ws://localhost:8000", help="server ws:// base URL")
    ap.add_argument("--concurrency", type=int, default=5, help="simultaneous WS generations")
    ap.add_argument("--num-questions", type=int, default=3, help="questions per generation (cost knob)")
    ap.add_argument("--timeout", type=float, default=120.0, help="per-request seconds before giving up")
    args = ap.parse_args()
    asyncio.run(main(args.host, args.concurrency, args.num_questions, args.timeout))
