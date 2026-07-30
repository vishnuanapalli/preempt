"""The store-on-change writer, against the real database.

Against the real one because every property that matters here is a database property:
`ON CONFLICT` semantics, `GREATEST` over a NULL, and what two writers racing on one primary
key actually do. A mock would assert my beliefs about Postgres rather than Postgres.

The test that earns its place is `test_the_written_count_differs_from_the_input_length`.
Never-ship #5 is a validity check arithmetically incapable of failing — in prior work an
"honest count, never `len(input)`" returned a value provably identical to `len(input)`. The
only way to know this one is not that is to make the two numbers differ and assert it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.ingest.writer import WriteResult, store_prices
from app.providers.base import REGION_WIDE, PriceObservation

pytestmark = pytest.mark.integration

TICK = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _observation(
    instance_type: str = "Standard_GS2",
    price: str = "0.225456",
    observed_at: datetime | None = None,
    os: str = "linux",
) -> PriceObservation:
    return PriceObservation(
        provider="azure",
        instance_type=instance_type,
        region="eastus",
        zone=REGION_WIDE,
        os=os,
        price_usd_hour=Decimal(price),
        source="measured",
        observed_at=observed_at or TICK,
    )


@pytest.fixture
async def session() -> AsyncSession:
    """A clean slate per test, and a real catalog row to write against.

    Truncating rather than rolling back: the concurrency test needs two sessions to see each
    other's committed work, which a wrapping transaction would prevent.
    """
    url = settings.test_database_url
    if not url:
        pytest.skip("PREEMPT_TEST_DATABASE_URL unset, so the writer's behaviour is UNPROVEN here")

    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    # Awaited, not `reachable()`. That helper wraps `asyncio.run`, which raises inside an
    # already-running loop — so calling it from an async fixture reported every test as
    # "database unreachable" while the container was healthy, and emitted a
    # "coroutine was never awaited" warning that was the only clue. Its own docstring says it
    # is synchronous because alembic owns its loop; that makes it unusable from here.
    try:
        async with engine.connect():
            pass
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"test database unreachable ({type(exc).__name__}), writer UNPROVEN here")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("TRUNCATE price_metric, pool, instance_catalog CASCADE"))
        await s.execute(
            text(
                "INSERT INTO instance_catalog (provider, instance_type, vcpu, memory_mb) "
                "VALUES ('azure', 'Standard_GS2', 4, 57344)"
            )
        )
        await s.commit()
        yield s
    await engine.dispose()


async def _price_rows(session: AsyncSession) -> list[tuple[Decimal, datetime]]:
    result = await session.execute(
        text("SELECT price_usd_hour, observed_at FROM price_metric ORDER BY observed_at")
    )
    return [(row[0], row[1]) for row in result]


async def test_the_first_observation_is_written(session: AsyncSession) -> None:
    result = await store_prices(session, [_observation()])
    await session.commit()

    assert result.prices_written == 1
    assert [p for p, _ in await _price_rows(session)] == [Decimal("0.225456")]


async def test_an_unchanged_price_writes_no_history_row(session: AsyncSession) -> None:
    """The whole point of store-on-change. Appending here spends the row budget on a row
    that says nothing happened."""
    await store_prices(session, [_observation()])
    await session.commit()

    later = await store_prices(session, [_observation(observed_at=TICK + timedelta(minutes=30))])
    await session.commit()

    assert later.unchanged == 1
    assert later.prices_written == 0
    assert len(await _price_rows(session)) == 1, "an unchanged price appended a second row"


async def test_an_unchanged_price_still_advances_last_seen(session: AsyncSession) -> None:
    """This is what makes a stale `last_seen` mean "ingestion stopped" rather than
    "nothing moved"."""
    await store_prices(session, [_observation()])
    await session.commit()
    first = (await session.execute(text("SELECT last_seen FROM pool"))).scalar_one()

    tick_two = TICK + timedelta(minutes=30)
    await store_prices(session, [_observation(observed_at=tick_two)])
    await session.commit()
    second = (await session.execute(text("SELECT last_seen FROM pool"))).scalar_one()

    assert second == tick_two
    assert second > first


async def test_last_seen_never_moves_backwards(session: AsyncSession) -> None:
    """A retried or delayed tick must not drag `last_seen` into the past — that would read
    as ingestion having stalled when it had not. GREATEST, not assignment."""
    await store_prices(session, [_observation(observed_at=TICK)])
    await session.commit()

    await store_prices(session, [_observation(observed_at=TICK - timedelta(hours=6))])
    await session.commit()

    assert (await session.execute(text("SELECT last_seen FROM pool"))).scalar_one() == TICK


async def test_a_changed_price_is_written(session: AsyncSession) -> None:
    await store_prices(session, [_observation(price="0.20")])
    await session.commit()
    result = await store_prices(
        session, [_observation(price="0.30", observed_at=TICK + timedelta(minutes=30))]
    )
    await session.commit()

    assert result.prices_written == 1
    assert [p for p, _ in await _price_rows(session)] == [Decimal("0.20"), Decimal("0.30")]


async def test_re_running_the_same_tick_creates_no_duplicates(session: AsyncSession) -> None:
    """Idempotence. A scheduler that fires twice, or a retry after a partial failure, must
    not double the history."""
    observations = [_observation(price="0.20")]
    first = await store_prices(session, observations)
    await session.commit()
    second = await store_prices(session, observations)
    await session.commit()

    assert first.prices_written == 1
    assert second.prices_written == 0, "the same tick wrote a second row"
    assert len(await _price_rows(session)) == 1


async def test_an_unknown_instance_type_is_counted_not_invented(session: AsyncSession) -> None:
    """Azure's retail feed carries no vcpu or memory, so a catalog row cannot be created from
    an observation without fabricating hardware specs behind a real price (D-019)."""
    result = await store_prices(session, [_observation(instance_type="Standard_NotInCatalog")])
    await session.commit()

    assert result.unknown_instance_type == 1
    assert result.prices_written == 0
    assert len(await _price_rows(session)) == 0


async def test_the_written_count_differs_from_the_input_length(session: AsyncSession) -> None:
    """Never-ship #5, directly. A count that always equals `len(input)` is not a count.

    Three observations in, one written: one is unchanged, one has an instance type that is not
    in the catalog. If `prices_written` ever equals `observed` here, it is reporting the input
    back rather than what the database did.
    """
    await store_prices(session, [_observation(price="0.20")])
    await session.commit()

    batch = [
        _observation(price="0.20", observed_at=TICK + timedelta(minutes=30)),  # unchanged
        _observation(price="0.99", observed_at=TICK + timedelta(minutes=30), os="windows"),  # new
        _observation(instance_type="Standard_Missing"),  # not in the catalog
    ]
    result = await store_prices(session, batch)
    await session.commit()

    assert result.observed == 3
    assert result.prices_written == 1
    assert result.prices_written != result.observed, "the count is echoing the input length"
    assert result.unchanged == 1
    assert result.unknown_instance_type == 1


async def test_every_observation_lands_in_exactly_one_bucket() -> None:
    """The counts are only trustworthy if they partition the input. Needs no database."""
    with pytest.raises(ValueError, match="accounted for"):
        WriteResult(observed=5, prices_written=1, unchanged=1, unknown_instance_type=1)


async def test_parallel_writers_lose_no_update(session: AsyncSession) -> None:
    """Two writers, one pool, the same tick. Exactly one row, and exactly one of them says
    it wrote it — the other must report 0 rather than raising or double-counting.

    This is the property `ON CONFLICT DO NOTHING RETURNING` is chosen for, and it cannot be
    established with one session: each writer needs its own connection and its own commit.
    """
    url = settings.test_database_url
    assert url is not None
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def writer() -> WriteResult:
        async with factory() as s:
            result = await store_prices(s, [_observation(price="0.42")])
            await s.commit()
            return result

    try:
        results = await asyncio.gather(writer(), writer(), writer(), return_exceptions=True)
    finally:
        await engine.dispose()

    raised = [r for r in results if isinstance(r, BaseException)]
    assert not raised, f"a concurrent writer raised instead of conceding: {raised}"

    written = [r.prices_written for r in results if isinstance(r, WriteResult)]
    assert sum(written) == 1, f"expected exactly one writer to insert the row, got {written}"
    assert len(await _price_rows(session)) == 1
    assert (await session.execute(text("SELECT count(*) FROM pool"))).scalar_one() == 1, (
        "concurrent writers created duplicate pools for one identity"
    )
