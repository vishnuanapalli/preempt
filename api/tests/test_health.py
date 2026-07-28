"""The health endpoint is what the uptime monitor watches, so its contract is tested.

The freshness assertion is the one that matters: `None` means "no observation exists",
and `0` would read as "observed just now". Conflating them would make a dead ingestion
pipeline look healthy — never-ship item 11, silence.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_ok() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_freshness_is_none_not_zero_when_no_observation_exists() -> None:
    body = client.get("/api/v1/health").json()
    assert body["observation_age_seconds"] is None
    assert body["observation_age_seconds"] != 0


def test_cadence_is_reported_so_a_monitor_can_derive_staleness() -> None:
    body = client.get("/api/v1/health").json()
    assert body["ingest_interval_seconds"] == 1800
