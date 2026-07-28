"""Liveness and freshness.

Freshness matters more than liveness here. A service that is up but whose ingestion
stopped six hours ago looks healthy and is not, and on a free tier a silently suspended
scheduler is a realistic failure. `observation_age_seconds` is what an external uptime
monitor watches.

The database and ingestion fields are placeholders in Sprint 0 — there is no database yet.
They are `None`, never `0`, because zero means "fresh" and would be a lie.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = Field(description="'ok' when the service can serve requests.")
    environment: str
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
    ingest_interval_seconds: int


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        database=None,
        observation_age_seconds=None,
        ingest_interval_seconds=settings.ingest_interval_seconds,
    )
