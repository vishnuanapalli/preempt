"""The test-database guard is the one setting that prevents an irreversible mistake.

A test suite pointed at the application database will eventually truncate it. In prior
work in this domain that exact thing happened: a fixture truncated the database the demo
ran on, destroying the dataset and then breaking the next backfill through orphaned rows.

The guard is worth a test because a guard that has never been seen to fire is
indistinguishable from one that does not work.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_rejects_identical_app_and_test_database_urls() -> None:
    url = "postgresql+asyncpg://u:p@localhost:5433/preempt"
    with pytest.raises(ValidationError, match="must not equal"):
        Settings(database_url=url, test_database_url=url)


def test_rejects_identical_urls_differing_only_by_whitespace() -> None:
    url = "postgresql+asyncpg://u:p@localhost:5433/preempt"
    with pytest.raises(ValidationError, match="must not equal"):
        Settings(database_url=url, test_database_url=f"  {url}  ")


def test_accepts_genuinely_different_databases() -> None:
    s = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5433/preempt",
        test_database_url="postgresql+asyncpg://u:p@localhost:5434/preempt_test",
    )
    assert s.database_url != s.test_database_url


def test_cadence_floor_rejects_a_value_that_would_exhaust_the_compute_budget() -> None:
    """600s is the floor. A 5-minute tick keeps the database permanently awake and
    exhausts the month's compute around day 16 — see D-002."""
    with pytest.raises(ValidationError):
        Settings(ingest_interval_seconds=300)


def test_production_rejects_an_unpooled_database_url() -> None:
    """`db/session.py` explains `statement_cache_size=0` by asserting production is pooled.
    Until this validator existed, that assertion was enforced by nothing — and an unpooled
    URL does not fail at startup, it fails sporadically under concurrency weeks later."""
    with pytest.raises(ValidationError, match="pooled endpoint"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://u:p@ep-x.example.com/preempt",
        )


def test_production_accepts_the_pooled_endpoint() -> None:
    s = Settings(
        environment="production",
        database_url="postgresql+asyncpg://u:p@ep-x-pooler.example.com/preempt",
    )
    assert "-pooler" in s.database_url


def test_local_is_not_required_to_be_pooled() -> None:
    """Local Postgres has no pooler and needs none. A guard that fires everywhere gets
    switched off everywhere."""
    s = Settings(
        environment="local",
        database_url="postgresql+asyncpg://u:p@localhost:5433/preempt",
    )
    assert s.database_url.endswith("/preempt")


def test_no_credential_defaults() -> None:
    """A committed development secret is never-ship #22.

    `_env_file=None` matters: without it pydantic-settings loads the developer's local
    .env, and the test passes or fails based on whatever happens to be on that machine
    rather than on what the code declares. That is how a test ends up asserting
    something other than what it claims to.
    """
    s = Settings(_env_file=None)
    assert s.api_key == ""
    assert s.database_url == ""
