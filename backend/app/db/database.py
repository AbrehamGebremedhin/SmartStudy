from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,          # Verify connections are alive before use
    pool_recycle=1800,           # Recycle connections every 30 minutes
    connect_args={
        "server_settings": {
            "statement_timeout": "30000",   # 30 seconds per statement
            "lock_timeout": "10000",        # 10 seconds waiting for locks
        }
    },
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
