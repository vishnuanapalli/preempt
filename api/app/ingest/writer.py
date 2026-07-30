"""Store-on-change writer. A price row exists only where the price actually moved.

`01-DESIGN.md`: at ~100 bytes a row against 0.5 GB, appending every observation for 500
pools every 30 minutes would spend the budget on rows that say nothing. So a re-observed
unchanged price updates `pool.last_seen` and writes no history row — which is also what
makes a stale `last_seen` mean "ingestion stopped" rather than "nothing moved".

**Every count comes from the database, never from the input.** Never-ship #5 is a check
that is arithmetically incapable of failing: in prior work an "honest count, never
`len(input)`" returned a value provably identical to `len(input)`. Here `prices_written` is
the number of rows `INSERT ... RETURNING` actually produced, so a conflict, a skip, or a
concurrent writer that got there first all move it — and `test_the_written_count_differs_
from_the_input_length` exists to prove it can.

**The catalog is not written here, and that is deliberate.** `instance_catalog` requires
`vcpu` and `memory_mb`; Azure's retail price feed returns neither. Inventing them would put
fabricated hardware specs behind a real price, so an observation whose `(provider,
instance_type)` is not already in the catalog is counted as `unknown_instance_type` and
skipped. See D-019. Pools *are* created on demand, because an observation carries everything
a pool needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.base import PriceObservation

#: Postgres SQLSTATEs that mean "try again", not "you are wrong":
#: 40P01 deadlock_detected, 40001 serialization_failure.
_RETRYABLE = {"40P01", "40001"}

#: Two retries. A deadlock needs one participant to back off, and Postgres has already killed
#: one of them by the time this sees the error, so the second attempt normally finds the row
#: committed and takes the DO NOTHING path.
_MAX_ATTEMPTS = 3


def _is_retryable(error: DBAPIError) -> bool:
    return getattr(error.orig, "sqlstate", None) in _RETRYABLE or any(
        code in str(error.orig) for code in ("DeadlockDetected", "SerializationFailure")
    )


@dataclass(frozen=True)
class WriteResult:
    """What the database did, not what was asked of it."""

    observed: int
    #: Rows `INSERT ... RETURNING` actually produced. Not the number of inserts attempted.
    prices_written: int
    #: Observations whose price matched the newest stored price for that pool.
    unchanged: int
    #: Observations skipped because their instance type is not in the catalog. Counted rather
    #: than dropped: silence here would look like the provider offering fewer machines.
    unknown_instance_type: int

    def __post_init__(self) -> None:
        accounted = self.prices_written + self.unchanged + self.unknown_instance_type
        if accounted != self.observed:
            raise ValueError(
                f"{self.observed} observations but {accounted} accounted for "
                f"({self.prices_written} written, {self.unchanged} unchanged, "
                f"{self.unknown_instance_type} unknown). Every observation must land in "
                "exactly one bucket, or the counts are decoration."
            )


_CATALOG_ID = text(
    "SELECT id FROM instance_catalog WHERE provider = :provider AND instance_type = :itype"
)

# DO UPDATE rather than DO NOTHING, for two reasons: it returns the id whether the row was
# new or not, and it advances last_seen on every observation, changed or not.
#
# GREATEST, because observations can arrive out of order — a retried tick must not drag
# last_seen backwards. Postgres's GREATEST ignores NULLs, so the first observation on a pool
# with no last_seen still sets it.
_UPSERT_POOL = text("""
    INSERT INTO pool (catalog_id, region, zone, os, last_seen)
    VALUES (:catalog_id, :region, :zone, :os, :seen)
    ON CONFLICT (catalog_id, region, zone, os)
    DO UPDATE SET last_seen = GREATEST(pool.last_seen, EXCLUDED.last_seen)
    RETURNING id
""")

_NEWEST_PRICE = text("""
    SELECT price_usd_hour FROM price_metric
    WHERE pool_id = :pool_id
    ORDER BY observed_at DESC
    LIMIT 1
""")

# ON CONFLICT DO NOTHING makes a re-run idempotent, and RETURNING is what makes the count
# honest: a row that lost the race to a concurrent writer returns nothing and is not counted.
_INSERT_PRICE = text("""
    INSERT INTO price_metric (pool_id, observed_at, price_usd_hour, source)
    VALUES (:pool_id, :observed_at, :price, :source)
    ON CONFLICT (pool_id, observed_at) DO NOTHING
    RETURNING pool_id
""")


async def store_prices(session: AsyncSession, observations: list[PriceObservation]) -> WriteResult:
    """Write only what changed. Returns what the database did.

    One round trip per observation rather than a batch. At 500 pools on a 30-minute tick that
    is ~1,500 statements per run against a database that is idle the rest of the time, which
    is well inside budget — and store-on-change means the write set shrinks as prices settle.
    Batching is a real optimisation and belongs with S-015's measured row counts rather than
    a guess now.
    """
    written = unchanged = unknown = 0

    for observation in observations:
        # Each observation is written inside a SAVEPOINT so a deadlock can be retried without
        # discarding the whole tick. Found by the concurrency test rather than reasoned about:
        # three writers racing on one new pool deadlocked, because the pool upsert holds a row
        # lock while the first insert into a hypertable takes a table-level lock to create its
        # chunk. Postgres kills one participant; the writes here are idempotent, so the honest
        # remedy is to let the survivor retry rather than to pretend it cannot happen.
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with session.begin_nested():
                    outcome = await _store_one(session, observation)
            except DBAPIError as error:
                if not _is_retryable(error) or attempt == _MAX_ATTEMPTS:
                    raise
                continue
            if outcome == "written":
                written += 1
            elif outcome == "unknown":
                unknown += 1
            else:
                unchanged += 1
            break

    return WriteResult(
        observed=len(observations),
        prices_written=written,
        unchanged=unchanged,
        unknown_instance_type=unknown,
    )


async def _store_one(session: AsyncSession, observation: PriceObservation) -> str:
    """One observation. Returns "written", "unchanged" or "unknown"."""
    catalog_id = (
        await session.execute(
            _CATALOG_ID,
            {"provider": observation.provider, "itype": observation.instance_type},
        )
    ).scalar_one_or_none()
    if catalog_id is None:
        return "unknown"

    pool_id = (
        await session.execute(
            _UPSERT_POOL,
            {
                "catalog_id": catalog_id,
                "region": observation.region,
                "zone": observation.zone,
                "os": observation.os,
                "seen": observation.observed_at,
            },
        )
    ).scalar_one()

    newest = (await session.execute(_NEWEST_PRICE, {"pool_id": pool_id})).scalar_one_or_none()
    if newest is not None and newest == observation.price_usd_hour:
        return "unchanged"

    inserted = (
        await session.execute(
            _INSERT_PRICE,
            {
                "pool_id": pool_id,
                "observed_at": observation.observed_at,
                "price": observation.price_usd_hour,
                "source": observation.source,
            },
        )
    ).scalar_one_or_none()
    # None means the row already existed, or a concurrent writer won. Either way no row
    # was written here, and counting the attempt would be counting the intent.
    return "unchanged" if inserted is None else "written"
