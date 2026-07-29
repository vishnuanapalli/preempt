"""Database engine and session factory.

Two settings here are not defaults and would be silent, intermittent failures if left
out — both are consequences of running against a serverless Postgres that suspends.

`statement_cache_size=0` — production connects through Neon's pooled endpoint, which is
pgbouncer in transaction mode. Transaction pooling does not support prepared statements,
and asyncpg prepares by default. The failure is not at startup: it appears later as
sporadic `InvalidSQLStatementName` errors under concurrency, when a cached statement name
is reused on a connection that no longer has it.

`pool_pre_ping=True` — the database scale-to-zeros after five minutes and cannot be
configured otherwise on the free plan. Pooled connections held across a suspend are dead
on the other side, and without a pre-ping the first request after an idle period fails
rather than reconnecting. On a demo that is idle most of the time, that first request is
usually the one a person is watching.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        # Small pool: the free instance has 0.1 vCPU and the database has its own
        # connection ceiling. A large pool would exhaust the latter without helping
        # the former.
        pool_size=3,
        max_overflow=2,
        pool_pre_ping=True,
        # Recycle below any plausible idle-disconnect window on the provider side.
        pool_recycle=280,
        connect_args={"statement_cache_size": 0},
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "PREEMPT_DATABASE_URL is not set. Copy .env.example to api/.env and fill it in."
            )
        _engine = _build_engine(settings.database_url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One session per request, always closed."""
    async with get_session_factory()() as session:
        yield session
