"""Health and readiness are split for a cost reason, so the split itself is tested.

The database scale-to-zeros after five minutes and cannot be configured otherwise on the
free plan, so any query wakes it for a five-minute minimum. An uptime monitor polling a
database-reading endpoint every fifteen minutes would hold it awake roughly a third of
the month — see D-009. `/health` must therefore stay free of database fields, and a test
enforces that rather than a comment asking politely.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_ok() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_exposes_no_database_backed_field() -> None:
    """Fails if anyone adds a field to /health that would require a query.

    This is the actual guard on the compute budget. Without it, a well-meaning change
    turns the cheap endpoint into an expensive one and nothing complains until the
    database suspends mid-month.
    """
    body = client.get("/api/v1/health").json()
    forbidden = {"database", "observation_age_seconds", "stale"}
    assert forbidden.isdisjoint(body.keys()), (
        f"/health must not expose database-backed fields: {forbidden & set(body.keys())}"
    )


def test_ready_reports_freshness_as_none_not_zero() -> None:
    """None means 'nothing observed'. Zero would read as 'observed just now'.

    Conflating them makes a dead ingestion pipeline look healthy — never-ship #11.
    """
    body = client.get("/api/v1/ready").json()
    assert body["observation_age_seconds"] is None
    assert body["observation_age_seconds"] != 0


def test_cadence_is_reported_so_a_monitor_can_derive_staleness() -> None:
    body = client.get("/api/v1/health").json()
    assert body["ingest_interval_seconds"] == 1800
