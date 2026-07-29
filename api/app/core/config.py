"""Application settings.

Every value is read from the environment. Nothing here carries a real credential as a
default — a committed development secret is item 22 on the never-ship list.

Several defaults are *derived* rather than chosen. Where that is the case the comment
says what they were derived from, because a number with no derivation gets "tuned" by
someone later who does not know it was load-bearing.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PREEMPT_", env_file=".env", extra="ignore")

    #: Free-form label for the running environment, surfaced by /health.
    environment: str = "local"

    #: Async SQLAlchemy URL. Empty until a database is configured (Sprint 0).
    database_url: str = ""

    #: Integration tests connect here. Must differ from `database_url` — see the
    #: validator below.
    test_database_url: str = ""

    #: Authenticates writes. No default: never-ship #22.
    api_key: str = ""

    #: Ingestion cadence. Derived from Neon's monthly compute budget, not chosen by
    #: preference: any query wakes the database for a five-minute minimum, so a
    #: shorter cadence exhausts the month's compute before the month ends (D-002).
    ingest_interval_seconds: int = Field(default=1800, ge=600)

    #: Observations older than this are deleted on a schedule.
    retention_days: int = Field(default=90, ge=1)

    #: Hard cap on tracked pools, derived from the 0.5 GB storage limit at a measured
    #: ~98 bytes per row. Exceeding it risks exhausting storage mid-month.
    max_tracked_pools: int = Field(default=500, ge=1)

    @model_validator(mode="after")
    def production_database_must_be_pooled(self) -> Settings:
        """Refuse to start in production against an unpooled endpoint.

        `app/db/session.py` sets `statement_cache_size=0` and explains it by asserting that
        production connects through Neon's pooled endpoint. Nothing enforced that, so the
        docstring was a claim about configuration rather than a property of it — and the
        failure it guards against is the worst kind: not a startup error, but sporadic
        `InvalidSQLStatementName` under concurrency, weeks later.

        Pooling is mandatory under D-010, not a preference. Only checked when a URL is
        actually set, so the current state — production running with no database
        configured — is unaffected.
        """
        if self.environment == "production" and self.database_url:
            if "-pooler" not in self.database_url:
                raise ValueError(
                    "PREEMPT_DATABASE_URL must use Neon's pooled endpoint in production "
                    "(the host contains '-pooler'). Pooling is mandatory under D-010: the "
                    "engine is configured for transaction pooling and an unpooled URL "
                    "fails later, intermittently, under concurrency."
                )
        return self

    @model_validator(mode="after")
    def test_database_must_differ(self) -> Settings:
        """Refuse to start if the test database is the application database.

        This is a guard against a specific incident, not a hypothetical. In prior work
        in this domain a test fixture truncated the same database the demo ran on,
        destroying the demo dataset and then breaking the next backfill through the
        orphaned rows it left behind. Comparing the two URLs costs nothing and makes
        that failure impossible rather than merely discouraged.
        """
        if self.database_url and self.test_database_url:
            if self.database_url.strip() == self.test_database_url.strip():
                raise ValueError(
                    "PREEMPT_TEST_DATABASE_URL must not equal PREEMPT_DATABASE_URL. "
                    "Integration tests truncate tables; pointing them at the application "
                    "database will destroy it."
                )
        return self


settings = Settings()
