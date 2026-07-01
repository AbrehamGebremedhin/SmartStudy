"""Job-queue integration tests: retry-then-succeed and SKIP LOCKED no double-claim.

Drives the worker primitives (_claim_one / _process) directly against the test DB
so behaviour is deterministic and doesn't depend on the background pool timing.
"""
import asyncio

import pytest
from sqlalchemy import select, update

from app.db.models import Job, JobStatus
from app.services import jobs


@pytest.fixture(autouse=True)
def _use_test_db(_patch_app_engine):
    """jobs.* read database.AsyncSessionLocal at call time; this fixture patches it."""
    yield


async def test_retry_then_succeed(TestSessionLocal):
    calls = {"n": 0}

    async def flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient boom")
        return {"echo": payload["x"]}

    jobs.register("test_flaky", flaky)
    job_id = await jobs.submit("test_flaky", {"x": 7}, max_attempts=3)

    # Attempt 1: claim + process -> fails -> requeued with future run_after, attempts=1.
    await jobs._process(await jobs._claim_one())
    async with TestSessionLocal() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        assert job.status == JobStatus.queued.value
        assert job.attempts == 1
        assert job.run_after > job.created_at        # backoff pushed it into the future

    # Skip the backoff wait: make it ready now.
    async with TestSessionLocal() as db:
        await db.execute(update(Job).where(Job.id == job_id).values(run_after=job.created_at))
        await db.commit()

    # Attempt 2: succeeds.
    await jobs._process(await jobs._claim_one())
    state = await jobs.get_job(job_id)
    assert state["status"] == JobStatus.done.value
    assert state["result"] == {"echo": 7}
    assert calls["n"] == 2


async def test_skip_locked_no_double_claim():
    jobs.register("test_noop", lambda p: asyncio.sleep(0, {"ok": True}))
    await jobs.submit("test_noop", {})

    # Two workers race for the single ready job; SKIP LOCKED must hand it to exactly one.
    a, b = await asyncio.gather(jobs._claim_one(), jobs._claim_one())
    claimed = [c for c in (a, b) if c is not None]
    assert len(claimed) == 1


async def test_submit_and_wait_woken_by_finish():
    """With a 60s fallback poll, submit_and_wait can only return in time via the
    in-process event set by _finish — proves the wake path, not DB polling."""
    jobs.register("test_wake", lambda p: asyncio.sleep(0, {"v": p["v"]}))

    async def worker():
        while True:
            claim = await jobs._claim_one()
            if claim:
                await jobs._process(claim)
                return
            await asyncio.sleep(0.02)

    result, _ = await asyncio.wait_for(
        asyncio.gather(
            jobs.submit_and_wait("test_wake", {"v": 42}, fallback_poll=60.0),
            worker(),
        ),
        timeout=10.0,
    )
    assert result == {"v": 42}


async def test_failure_exhausts_retries():
    async def always_fail(payload):
        raise RuntimeError("nope")

    jobs.register("test_fail", always_fail)
    job_id = await jobs.submit("test_fail", {}, max_attempts=1)

    await jobs._process(await jobs._claim_one())   # attempts -> 1 == max -> failed
    state = await jobs.get_job(job_id)
    assert state["status"] == JobStatus.failed.value
    assert "nope" in state["error"]
