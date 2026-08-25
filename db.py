"""Engine and session factory construction, kept separate from models.py
so tests can point at sqlite/aiosqlite while production uses Postgres."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base


def create_engine(database_url: str) -> AsyncEngine:
    # e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """Creates tables directly from ORM metadata. Fine for getting a
    first deployment running; once you have real data, switch to Alembic
    migrations instead of calling this against an existing database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
