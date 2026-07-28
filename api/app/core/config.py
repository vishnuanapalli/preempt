"""Application settings.

Every value is read from the environment. Nothing here carries a real credential as a
default — a committed development secret is item 22 on the never-ship list.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PREEMPT_", env_file=".env", extra="ignore")

    #: Free-form label for the running environment, surfaced by /health.
    environment: str = "local"

    #: Ingestion cadence. Derived from Neon's monthly compute budget, not chosen by
    #: preference — see D-002. Changing it changes how fast the free tier is consumed.
    ingest_interval_seconds: int = 1800

    #: Observations older than this are deleted on a schedule. See D-002 and the row
    #: budget in the design document.
    retention_days: int = 90

    #: Hard cap on tracked pools, derived from the 0.5 GB storage limit.
    max_tracked_pools: int = 500


settings = Settings()
