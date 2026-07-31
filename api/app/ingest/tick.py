"""One ingestion tick: fetch from every provider, write what changed, report what happened.

This is the unit the scheduler runs. D-002 fixes the cadence at 30 minutes and the floor at 10,
because Neon wakes for a five-minute minimum on any query — a shorter tick keeps the database
permanently awake and spends the month's compute before the month ends.

**A failing provider does not fail the tick.** Azure is the only measured source and it
rate-limits; if it is unavailable, the simulated providers still have work to do and the honest
outcome is a partial tick that says which provider failed, not a lost one. `TickResult.failures`
carries them, and a caller that wants to treat any failure as fatal can — the decision is not
made here.

**Nothing is invented on the way through.** Un-catalogued instance types are counted, not
guessed (D-019); a provider that answers in an unreadable shape raises rather than contributing
partial data; and simulated rows stay labelled `simulated` end to end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.writer import WriteResult, store_prices
from app.providers import azure, simulated
from app.providers.base import ProviderError

#: Regions ingested per tick. One per provider keeps the row budget honest: `01-DESIGN.md` caps
#: tracked pools at 500, and every region added multiplies the pool count by the catalog size.
REGIONS = {"azure": "eastus", "aws": "us-east-1", "gcp": "us-central1"}

_CATALOG_FOR = text(
    "SELECT instance_type, vcpu FROM instance_catalog WHERE provider = :provider "
    "ORDER BY instance_type"
)


@dataclass(frozen=True)
class TickResult:
    """What one tick did, per provider, including what it could not do."""

    started_at: datetime
    writes: dict[str, WriteResult] = field(default_factory=dict)
    #: provider -> why it produced nothing. A tick with failures is a partial tick, not a
    #: failed one, and the distinction has to survive into whatever reads this.
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def prices_written(self) -> int:
        return sum(w.prices_written for w in self.writes.values())

    @property
    def observed(self) -> int:
        return sum(w.observed for w in self.writes.values())

    def summary(self) -> str:
        parts = [
            f"{provider}: {w.prices_written} written / {w.observed} observed"
            + (f", {w.unknown_instance_type} uncatalogued" if w.unknown_instance_type else "")
            for provider, w in sorted(self.writes.items())
        ]
        parts += [f"{provider}: FAILED ({why})" for provider, why in sorted(self.failures.items())]
        return "; ".join(parts) or "nothing ingested"


async def _catalog_for(session: AsyncSession, provider: str) -> list[tuple[str, int]]:
    rows = await session.execute(_CATALOG_FOR, {"provider": provider})
    return [(instance_type, vcpu) for instance_type, vcpu in rows]


async def run_tick(
    session: AsyncSession,
    client: httpx.Client,
    observed_at: datetime | None = None,
) -> TickResult:
    """Fetch and store one round of observations from all three providers.

    The client is injected for the same reason the Azure provider takes one: so a test can
    serve recorded payloads rather than rate-limit itself against the live endpoint.
    """
    stamp = observed_at or datetime.now(UTC)
    writes: dict[str, WriteResult] = {}
    failures: dict[str, str] = {}

    # Azure first, because it is the only measured source and the only one that can fail for
    # reasons outside this process.
    try:
        measured = azure.fetch_spot_prices(client, REGIONS["azure"], stamp)
        writes["azure"] = await store_prices(session, list(measured.observations))
    except ProviderError as error:
        failures["azure"] = str(error)

    for provider in ("aws", "gcp"):
        catalog = await _catalog_for(session, provider)
        if not catalog:
            # Not an error and not silent: the seed has not run for this provider, and saying
            # so is what stops "no data" being read as "no prices exist".
            failures[provider] = "no catalog rows; run scripts/seed.py"
            continue
        result = simulated.fetch_spot_prices(provider, catalog, REGIONS[provider], stamp)
        writes[provider] = await store_prices(session, list(result.observations))

    return TickResult(started_at=stamp, writes=writes, failures=failures)
