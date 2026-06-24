#!/usr/bin/env python3
"""Load-test the real job queue without touching any LLM.

Registers a fake handler that just sleeps for `--latency` seconds (stand-in for a
generation), fires `--jobs` of them at the actual worker pool + autoscaler +
Postgres, and reports the numbers that answer "how many concurrent users":

    throughput (jobs/min), peak concurrency the autoscaler reached, and the
    end-to-end latency percentiles a user would feel (queue wait + processing).

This exercises the genuine bottleneck (MAX_WORKERS, DB pool, SKIP LOCKED, the
supervisor) — not a synthetic one. To find your real ceiling, set --latency to
your measured average generation time (watch the server logs for one).

Usage
-----
    # 50 jobs, each simulating a 12s generation, default 8 workers:
    uv run python scripts/loadtest_queue.py --jobs 50 --latency 12

    # try a bigger pool:
    uv run python scripts/loadtest_queue.py --jobs 100 --latency 12 --max-workers 16
"""
import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ on path

from sqlalchemy import delete, func, select  # noqa: E402

from app.db import database  # noqa: E402
from app.db.models import Job, JobStatus  # noqa: E402
from app.services import jobs  # noqa: E402

JOB_TYPE = "loadtest"


async def _running_count() -> int:
    async with database.AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(Job)
            .where(Job.type == JOB_TYPE, Job.status == JobStatus.running.value)
        )).scalar_one()


async def _status_counts() -> dict:
    async with database.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Job.status, func.count()).select_from(Job)
            .where(Job.type == JOB_TYPE).group_by(Job.status)
        )).all()
    return {s: c for s, c in rows}


async def _cleanup() -> None:
    async with database.AsyncSessionLocal() as db:
        await db.execute(delete(Job).where(Job.type == JOB_TYPE))
        await db.commit()


async def main(n: int, latency: float, max_workers: int | None) -> None:
    # Don't pull in the generation/agent stack — we only want the pool mechanics.
    jobs._register_default_handlers = lambda: None
    jobs.register(JOB_TYPE, lambda _p: asyncio.sleep(latency, {}))
    if max_workers:
        jobs.MAX_WORKERS = max_workers

    await _cleanup()
    print(f"Submitting {n} jobs · {latency}s each · workers {jobs.MIN_WORKERS}-{jobs.MAX_WORKERS}")
    ideal = jobs.MAX_WORKERS / latency
    print(f"Ideal ceiling at full scale: {ideal:.2f} jobs/s ({ideal * 60:.0f}/min)\n")

    await asyncio.gather(*(jobs.submit(JOB_TYPE, {}) for _ in range(n)))
    await jobs.start()

    t0 = time.monotonic()
    peak = 0
    while True:
        counts = await _status_counts()
        done = counts.get(JobStatus.done.value, 0) + counts.get(JobStatus.failed.value, 0)
        peak = max(peak, await _running_count())
        if done >= n:
            break
        await asyncio.sleep(0.2)
    elapsed = time.monotonic() - t0
    await jobs.stop()

    # End-to-end latency each "user" felt = finish (updated_at) - submit (created_at).
    async with database.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Job.created_at, Job.updated_at).where(Job.type == JOB_TYPE)
        )).all()
    lat = sorted((u - c).total_seconds() for c, u in rows)

    print(f"Done {n} jobs in {elapsed:.1f}s")
    print(f"Throughput:        {n / elapsed:.2f} jobs/s ({n / elapsed * 60:.0f}/min)")
    print(f"Peak concurrency:  {peak} workers (autoscaler reached this)")
    print(f"User wait p50/p95/max: {_pct(lat, 50):.1f}s / {_pct(lat, 95):.1f}s / {lat[-1]:.1f}s")

    await _cleanup()


def _pct(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    return statistics.quantiles(values, n=100)[p - 1] if len(values) > 1 else values[0]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=50, help="total jobs to fire")
    ap.add_argument("--latency", type=float, default=12.0, help="seconds each job sleeps (your avg gen time)")
    ap.add_argument("--max-workers", type=int, help="override jobs.MAX_WORKERS for this run")
    args = ap.parse_args()
    asyncio.run(main(args.jobs, args.latency, args.max_workers))
