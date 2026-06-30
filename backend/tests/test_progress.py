"""Round-trip + upsert checks for the /progress gamification-sync endpoint."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_get_empty_returns_null(client):
    res = await client.get("/api/progress")
    assert res.status_code == 200
    assert res.json() == {"profile": None, "updated_at": None}


async def test_put_then_get_roundtrips(client):
    profile = {"v": 1, "xp": 120, "streak": {"current": 3, "best": 5}}
    put = await client.put("/api/progress", json={"profile": profile})
    assert put.status_code == 200
    assert put.json()["profile"] == profile

    got = await client.get("/api/progress")
    assert got.json()["profile"] == profile
    assert got.json()["updated_at"] is not None


async def test_put_is_upsert(client):
    await client.put("/api/progress", json={"profile": {"xp": 10}})
    await client.put("/api/progress", json={"profile": {"xp": 99}})
    got = await client.get("/api/progress")
    assert got.json()["profile"] == {"xp": 99}  # second write replaces the first
