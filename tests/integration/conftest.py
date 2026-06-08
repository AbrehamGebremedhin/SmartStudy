"""
Integration-level conftest: autouse table cleanup between tests.
Only applies to tests/integration/** (pytest conftest scoping).
"""
import pytest
from app.db.database import Base


@pytest.fixture(autouse=True)
async def _clean_tables(db_engine):
    """Truncate all tables AFTER each integration test for isolation."""
    yield
    async with db_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
