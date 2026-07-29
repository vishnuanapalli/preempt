"""Liveness and readiness, deliberately split.

Freshness matters more than liveness: a service that is up but whose ingestion stopped six
hours ago looks healthy and is not, and on a free tier a silently suspended scheduler is a
realistic failure.

But reading freshness costs money here, and the arithmetic is why these are two endpoints
rather than one.

The database scale-to-zeros after five minutes of inactivity and cannot be configured
otherwise on the free plan, so *any* query wakes it for a five-minute minimum. An uptime
monitor polling a database-reading endpoint every fifteen minutes therefore holds the
compute awake roughly a third of the time — about 243 hours a month against a 400-hour
budget, before a single visitor loads the demo. The design's own 122-hour estimate counted
only the ingest tick and missed this (D-009).

So:
  /health — liveness only. Touches nothing. The uptime monitor polls this, for free.
  /ready  — reads the database and reports freshness. Polled hourly, which lands inside
            wake windows the 30-minute ingest tick already pays for.

Freshness is `None`, never `0`, when nothing has been observed. Zero reads as "just now"
and would make a dead pipeline look healthy.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Liveness. Deliberately carries no field that would require a database read."""

    status: str = Field(description="'ok' when the process can serve requests.")
    environment: str
    ingest_interval_seconds: int


class ReadyResponse(BaseModel):
    """Readiness. Reads the database, and therefore costs compute budget to call."""

    status: str
    database: str | None = Field(
        default=None,
        description="Database reachability. None until a database is configured (Sprint 0).",
    )
    observation_age_seconds: float | None = Field(
        default=None,
        description=(
            "Age of the newest observation. None when no observation exists — never 0, "
            "which would falsely read as fresh."
        ),
    )
    stale: bool | None = Field(
        default=None,
        description="True when the newest observation is older than two ingest intervals.",
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness. Safe to poll frequently — touches no external resource."""
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        ingest_interval_seconds=settings.ingest_interval_seconds,
    )


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Readiness and ingestion freshness. Poll hourly at most — see the module docstring.

    `status` reports what is true, which right now is that nothing is configured. It said
    `"ok"` until 2026-07-29, which is the one answer a readiness probe must never give
    while it is not ready: an orchestrator reading `"ok"` routes traffic here, and the
    fields that would have said otherwise are all `None` — indistinguishable, to anything
    reading them, from a database that is up and simply has no observations yet.
    """
    # Sprint 0 has no database. These stay None rather than being invented, per the
    # standing rule: defer, don't manufacture state a later sprint will create.
    if not settings.database_url:
        return ReadyResponse(
            status="not_configured",
            database=None,
            observation_age_seconds=None,
            stale=None,
        )
    return ReadyResponse(
        status="ok",
        database=None,
        observation_age_seconds=None,
        stale=None,
    )
