"""Provenance is a database constraint, not a convention. S-014.

`01-DESIGN.md`: every response carrying a price includes a non-nullable provenance object, and
a simulated price that loses its label is indistinguishable from a measured one — which would
make the whole comparison dishonest rather than merely incomplete.

So these tests go around the application entirely and write raw SQL. A model-level default or
a pydantic validator proves only that the *application* is careful; it says nothing about a
migration, a psql session, a future service, or a bulk load. The question is whether the
database would refuse, and the only way to know is to ask it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings
from app.db.models import HYPERTABLES, SOURCES

pytestmark = pytest.mark.integration


@pytest.fixture
async def conn() -> AsyncConnection:
    url = settings.test_database_url
    if not url:
        pytest.skip("PREEMPT_TEST_DATABASE_URL unset, so provenance is UNPROVEN here")
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as c:
            yield c
    except Exception as exc:
        pytest.skip(f"test database unreachable ({type(exc).__name__}), provenance UNPROVEN")
    finally:
        await engine.dispose()


async def _pool_id(conn: AsyncConnection) -> int:
    """A real catalog row and pool to hang observations off, rolled back afterwards."""
    catalog_id = (
        await conn.execute(
            text(
                "INSERT INTO instance_catalog (provider, instance_type, vcpu, memory_mb) "
                "VALUES ('azure', 'Standard_ProvenanceProbe', 2, 8192) RETURNING id"
            )
        )
    ).scalar_one()
    return (
        await conn.execute(
            text(
                "INSERT INTO pool (catalog_id, region, zone, os) "
                "VALUES (:c, 'eastus', 'region-wide', 'linux') RETURNING id"
            ),
            {"c": catalog_id},
        )
    ).scalar_one()


@pytest.mark.parametrize("table", HYPERTABLES)
async def test_a_row_without_provenance_is_refused(conn: AsyncConnection, table: str) -> None:
    """The criterion, asked of the database in raw SQL.

    Every fact table, not just `price_metric`: a capacity signal or an interruption event with
    no source is the same defect, and the one that gets forgotten is the one nobody wrote a
    test for. `HYPERTABLES` is read from the models, so a fourth fact table is covered the day
    it is added rather than the day someone remembers.
    """
    columns = {
        "price_metric": "price_usd_hour",
        "capacity_metric": "capacity_score",
        "interruption_event": "reclaimed_count",
    }
    values = {"price_metric": "0.05", "capacity_metric": "0.5", "interruption_event": "1"}

    async with conn.begin() as tx:
        pool_id = await _pool_id(conn)
        with pytest.raises((IntegrityError, DBAPIError)) as caught:
            await conn.execute(
                text(
                    f"INSERT INTO {table} (pool_id, observed_at, {columns[table]}) "  # noqa: S608
                    f"VALUES (:p, now(), {values[table]})"
                ),
                {"p": pool_id},
            )
        assert "source" in str(caught.value).lower(), (
            f"{table} rejected the row, but not because `source` was missing: {caught.value}"
        )
        await tx.rollback()


@pytest.mark.parametrize("table", HYPERTABLES)
async def test_an_explicit_null_source_is_refused(conn: AsyncConnection, table: str) -> None:
    """Omitting the column and passing NULL are different statements, and a default would make
    the first pass while the second still failed. Both must be refused."""
    columns = {
        "price_metric": ("price_usd_hour", "0.05"),
        "capacity_metric": ("capacity_score", "0.5"),
        "interruption_event": ("reclaimed_count", "1"),
    }
    column, value = columns[table]

    async with conn.begin() as tx:
        pool_id = await _pool_id(conn)
        with pytest.raises((IntegrityError, DBAPIError)):
            await conn.execute(
                text(
                    f"INSERT INTO {table} (pool_id, observed_at, {column}, source) "  # noqa: S608
                    f"VALUES (:p, now(), {value}, NULL)"
                ),
                {"p": pool_id},
            )
        await tx.rollback()


@pytest.mark.parametrize("table", HYPERTABLES)
async def test_an_unrecognised_source_is_refused(conn: AsyncConnection, table: str) -> None:
    """Non-null is not enough. `source = 'probably real'` carries no information and would
    silently join the measured rows in any query that filters on the known values."""
    columns = {
        "price_metric": ("price_usd_hour", "0.05"),
        "capacity_metric": ("capacity_score", "0.5"),
        "interruption_event": ("reclaimed_count", "1"),
    }
    column, value = columns[table]

    async with conn.begin() as tx:
        pool_id = await _pool_id(conn)
        with pytest.raises((IntegrityError, DBAPIError)) as caught:
            await conn.execute(
                text(
                    f"INSERT INTO {table} (pool_id, observed_at, {column}, source) "  # noqa: S608
                    f"VALUES (:p, now(), {value}, 'probably real')"
                ),
                {"p": pool_id},
            )
        assert "source" in str(caught.value).lower()
        await tx.rollback()


@pytest.mark.parametrize("table", HYPERTABLES)
@pytest.mark.parametrize("source", SOURCES)
async def test_the_known_sources_are_accepted(
    conn: AsyncConnection, table: str, source: str
) -> None:
    """The other half. A constraint that rejects everything would pass every test above and
    make the system unusable — this is what distinguishes "correctly strict" from "broken"."""
    columns = {
        "price_metric": ("price_usd_hour", "0.05"),
        "capacity_metric": ("capacity_score", "0.5"),
        "interruption_event": ("reclaimed_count", "1"),
    }
    column, value = columns[table]

    async with conn.begin() as tx:
        pool_id = await _pool_id(conn)
        await conn.execute(
            text(
                f"INSERT INTO {table} (pool_id, observed_at, {column}, source) "  # noqa: S608
                f"VALUES (:p, now(), {value}, :s)"
            ),
            {"p": pool_id, "s": source},
        )
        stored = (
            await conn.execute(
                text(f"SELECT source FROM {table} WHERE pool_id = :p"),  # noqa: S608
                {"p": pool_id},
            )
        ).scalar_one()
        assert stored == source
        await tx.rollback()


async def test_the_constraint_lives_in_the_database_not_the_model(conn: AsyncConnection) -> None:
    """Read from the catalog, so this cannot be satisfied by a model-level declaration.

    A `nullable=False` in SQLAlchemy and a `NOT NULL` in Postgres are different facts. The
    first is a promise the application makes; only the second survives a migration, a psql
    session, or anything that is not this application.
    """
    rows = await conn.execute(
        text("""
            SELECT c.table_name, c.is_nullable
            FROM information_schema.columns c
            WHERE c.table_schema = 'public' AND c.column_name = 'source'
            ORDER BY c.table_name
        """)
    )
    nullability = {table: is_nullable for table, is_nullable in rows}

    assert set(nullability) == set(HYPERTABLES), (
        f"expected a `source` column on every fact table, found {sorted(nullability)}"
    )
    nullable = [t for t, n in nullability.items() if n != "NO"]
    assert not nullable, f"`source` is nullable in the database on: {nullable}"
