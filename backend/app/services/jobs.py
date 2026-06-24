"""Postgres-backed async job queue.

The `jobs` table *is* the queue. A pool of asyncio worker tasks claims the oldest
ready job with `SELECT ... FOR UPDATE SKIP LOCKED`, runs the handler registered
for its type, and on failure re-queues it with exponential backoff until
`max_attempts` is reached. A supervisor grows/shrinks the worker count with the
backlog (the "autoscale"); a reaper requeues jobs whose worker died mid-run.

Why Postgres and not Redis/Celery: durability, restart-survival, and
multi-instance coordination come for free from SKIP LOCKED — no new dependency.

# ponytail: worker pool scales concurrency *within one process*. To scale across
# machines, run more app instances — SKIP LOCKED already prevents double-claims.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from app.core.exceptions import OutOfContextError
from app.db import database  # referenced lazily so tests can patch AsyncSessionLocal
from app.db.models import Job, JobStatus

logger = logging.getLogger(__name__)

# Tuning. MAX_WORKERS stays well under the DB pool (15 + 15 overflow) so claims
# and the WS result-polls never starve each other for connections.
MIN_WORKERS = 1
MAX_WORKERS = 8
POLL_IDLE_SECONDS = 1.0       # worker sleep when no job is ready
SUPERVISOR_INTERVAL = 3.0     # how often we re-check the backlog
LEASE_SECONDS = 300           # a `running` job older than this is presumed dead
MAX_BACKOFF_SECONDS = 60
BASE_BACKOFF_SECONDS = 2      # retry waits BASE * 2**(attempts-1), capped

Handler = Callable[[dict], Awaitable[dict]]
HANDLERS: dict[str, Handler] = {}


class JobFailed(Exception):
    """Raised by submit_and_wait when a job exhausts its retries."""


def register(job_type: str, handler: Handler) -> None:
    HANDLERS[job_type] = handler


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── public API ────────────────────────────────────────────────────────────────

async def submit(job_type: str, payload: dict, max_attempts: int = 3) -> uuid.UUID:
    async with database.AsyncSessionLocal() as db:
        job = Job(type=job_type, payload=payload, max_attempts=max_attempts)
        db.add(job)
        await db.commit()
        return job.id


async def get_job(job_id: uuid.UUID) -> dict:
    return await _job_state(job_id)


async def submit_and_wait(job_type: str, payload: dict,
                          timeout: float = 300.0, poll: float = 0.25) -> dict:
    """Submit a job and block until it finishes. Returns the handler's result dict.

    Raises OutOfContextError (preserved across the queue boundary), JobFailed on
    exhausted retries, or TimeoutError.
    """
    job_id = await submit(job_type, payload)
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        st = await _job_state(job_id)
        if st["status"] == JobStatus.done.value:
            return st["result"]
        if st["status"] == JobStatus.failed.value:
            _raise_failure(st["error"])
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"job {job_id} did not finish within {timeout}s")
        await asyncio.sleep(poll)


def _raise_failure(error: str | None) -> None:
    try:
        data = json.loads(error) if error else None
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict) and data.get("kind") == "out_of_context":
        raise OutOfContextError(data.get("message", ""), data.get("valid_options"))
    raise JobFailed(error or "job failed")


# ── claim / run ───────────────────────────────────────────────────────────────

async def _job_state(job_id: uuid.UUID) -> dict:
    async with database.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Job.status, Job.result, Job.error).where(Job.id == job_id)
        )).one_or_none()
    if row is None:
        return {"status": "missing", "result": None, "error": "job not found"}
    return {"status": row.status, "result": row.result, "error": row.error}


async def _claim_one() -> dict | None:
    """Atomically grab the oldest ready job and mark it running. None if idle."""
    async with database.AsyncSessionLocal() as db:
        async with db.begin():
            job = (await db.execute(
                select(Job)
                .where(Job.status == JobStatus.queued.value, Job.run_after <= _now())
                .order_by(Job.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if job is None:
                return None
            job.status = JobStatus.running.value
            job.locked_at = _now()
            job.attempts += 1
            return {"id": job.id, "type": job.type, "payload": job.payload,
                    "attempts": job.attempts, "max_attempts": job.max_attempts}


async def _process(claim: dict) -> None:
    handler = HANDLERS.get(claim["type"])
    try:
        if handler is None:
            raise RuntimeError(f"no handler registered for job type {claim['type']!r}")
        result = await handler(claim["payload"])
        await _finish(claim["id"], JobStatus.done.value, result=result)
    except asyncio.CancelledError:
        raise  # shutdown/scale-down: leave it `running` for the reaper to requeue
    except OutOfContextError as e:
        # Permanent domain error — don't burn retries; carry it across the boundary.
        await _finish(claim["id"], JobStatus.failed.value, error=json.dumps(
            {"kind": "out_of_context", "message": e.message, "valid_options": e.valid_options}))
    except Exception as e:  # noqa: BLE001 — any worker error must not kill the loop
        logger.exception("job %s (%s) failed on attempt %d/%d",
                         claim["id"], claim["type"], claim["attempts"], claim["max_attempts"])
        if claim["attempts"] >= claim["max_attempts"]:
            await _finish(claim["id"], JobStatus.failed.value, error=str(e))
        else:
            backoff = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * 2 ** (claim["attempts"] - 1))
            await _retry(claim["id"], error=str(e), backoff=backoff)


async def _finish(job_id: uuid.UUID, status: str, result: dict | None = None,
                  error: str | None = None) -> None:
    async with database.AsyncSessionLocal() as db:
        await db.execute(update(Job).where(Job.id == job_id).values(
            status=status, result=result, error=error, locked_at=None))
        await db.commit()


async def _retry(job_id: uuid.UUID, error: str, backoff: float) -> None:
    async with database.AsyncSessionLocal() as db:
        await db.execute(update(Job).where(Job.id == job_id).values(
            status=JobStatus.queued.value, error=error, locked_at=None,
            run_after=_now() + timedelta(seconds=backoff)))
        await db.commit()


# ── worker pool + autoscale ───────────────────────────────────────────────────

_workers: dict[int, asyncio.Task] = {}   # slot -> task; slots 0.._desired-1 stay filled
_desired = MIN_WORKERS
_supervisor_task: asyncio.Task | None = None
_reaper_task: asyncio.Task | None = None
_running = False


async def _worker(slot: int) -> None:
    # Exits gracefully when its slot is scaled out — but only *between* jobs, so an
    # in-flight generation is never interrupted by a scale-down.
    try:
        while _running and slot < _desired:
            claim = await _claim_one()
            if claim is None:
                await asyncio.sleep(POLL_IDLE_SECONDS)
                continue
            await _process(claim)
    finally:
        _workers.pop(slot, None)


def _spawn_missing() -> None:
    for slot in range(_desired):
        if slot not in _workers:
            _workers[slot] = asyncio.create_task(_worker(slot))


async def _ready_count() -> int:
    async with database.AsyncSessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(Job)
            .where(Job.status == JobStatus.queued.value, Job.run_after <= _now())
        )).scalar_one()


async def _supervisor() -> None:
    global _desired
    while _running:
        try:
            backlog = await _ready_count()
            _desired = min(MAX_WORKERS, MIN_WORKERS + backlog) if backlog else MIN_WORKERS
            _spawn_missing()
        except Exception:  # noqa: BLE001 — a transient DB hiccup must not stop autoscaling
            logger.exception("job supervisor tick failed")
        await asyncio.sleep(SUPERVISOR_INTERVAL)


async def _reaper() -> None:
    while _running:
        try:
            cutoff = _now() - timedelta(seconds=LEASE_SECONDS)
            async with database.AsyncSessionLocal() as db:
                await db.execute(update(Job).where(
                    Job.status == JobStatus.running.value, Job.locked_at < cutoff
                ).values(status=JobStatus.queued.value, locked_at=None))
                await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("job reaper tick failed")
        await asyncio.sleep(LEASE_SECONDS)


async def start() -> None:
    global _running, _desired, _supervisor_task, _reaper_task
    if _running:
        return
    _register_default_handlers()
    _running = True
    _desired = MIN_WORKERS
    _spawn_missing()
    _supervisor_task = asyncio.create_task(_supervisor())
    _reaper_task = asyncio.create_task(_reaper())
    logger.info("job queue started (workers %d-%d)", MIN_WORKERS, MAX_WORKERS)


async def stop() -> None:
    global _running
    _running = False
    tasks = list(_workers.values()) + [t for t in (_supervisor_task, _reaper_task) if t]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _workers.clear()


def _register_default_handlers() -> None:
    # Local imports: keep this module importable without pulling in the agent stack.
    from app.services.generation import (run_generate_flashcards, run_generate_mcqs,
                                          run_generate_notes)
    register("generate_mcq", lambda p: run_generate_mcqs(**p))
    register("generate_flashcards", lambda p: run_generate_flashcards(**p))
    register("generate_notes", lambda p: run_generate_notes(**p))
