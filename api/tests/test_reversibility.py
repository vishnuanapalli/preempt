"""Migrations are reversible — and this is the check that can say otherwise.

S-002 originally asked for `alembic downgrade base` then `upgrade head` to succeed. That
exits 0 against a migration whose `upgrade()` and `downgrade()` are both `pass`, which is
exactly what this project's baseline is, and it was reported as demo evidence. So the useful
question is not "are the migrations reversible" but "would this notice if they were not".

Six tests need no database. Three run against the real test database: the round trip, its
coverage, and one deliberately irreversible migration that must be reported as such — a
check nobody has watched fail is indistinguishable from one that cannot.

As of S-010 this covers real schema: two relational tables and three hypertables. Until
then `covered` was 0 and a strict xfail said so; it failed the day the tables landed, which
is what it was for, and it is gone.

Trimmed from 762 lines on 2026-07-29 (ledger R9/R10). What went: a 22-case mutation matrix
over the harness, chain-stepping tests for a chain of one, seven speculative object classes,
two of three sabotage shapes. In git at `22d656b`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import settings
from tests.reversibility import (
    RoundTrip,
    Snapshot,
    alembic_config,
    diff,
    reachable,
    run_round_trip,
    same_database,
    snapshot,
)

# ------------------------------------------------------------------ no database needed


def _snap(*objects: tuple[str, str, str]) -> Snapshot:
    return Snapshot(objects=tuple(sorted(objects)))


def test_identical_schemas_report_no_difference() -> None:
    s = _snap(("relation", "public.pool", "kind=r"), ("column", "public.pool.id", "type=integer"))
    assert diff(s, s) == []


def test_a_table_left_behind_is_reported() -> None:
    """What an empty downgrade produces: the upgrade's table is still there."""
    after = _snap(("relation", "public.pool", "kind=r"))
    assert diff(_snap(), after) == ["added relation public.pool: kind=r"]


def test_a_table_not_recreated_is_reported() -> None:
    before = _snap(("relation", "public.pool", "kind=r"))
    assert diff(before, _snap()) == ["removed relation public.pool: kind=r"]


def test_a_column_restored_with_a_different_shape_is_reported() -> None:
    """Comparing names only is how a nullability change survives a round trip unnoticed."""
    before = _snap(("column", "public.pool.price", "type=numeric null=false"))
    after = _snap(("column", "public.pool.price", "type=numeric null=true"))
    assert diff(before, after) == [
        "changed column public.pool.price: 'type=numeric null=false' -> 'type=numeric null=true'"
    ]


def test_a_round_trip_that_did_not_restore_the_schema_is_not_reversible() -> None:
    """The verdict itself. If this passes while `after_reverse` differs from `base`,
    nothing below it means anything."""
    head = _snap(("relation", "public.pool", "kind=r"))
    rt = RoundTrip(base=_snap(), head=head, after_reverse=head, after_reapply=head)
    assert not rt.reversible
    assert rt.differences == ["added relation public.pool: kind=r"]
    assert rt.covered == 1


def test_a_failed_re_application_is_not_reversible() -> None:
    """An empty `downgrade()` surfaces here, not in the diff: the second upgrade collides."""
    head = _snap(("relation", "public.pool", "kind=r"))
    rt = RoundTrip(
        base=_snap(),
        head=head,
        after_reverse=head,
        after_reapply=head,
        reapply_error='DuplicateTableError: relation "pool" already exists',
    )
    assert not rt.reversible
    assert rt.differences[-1].startswith("upgrading to head again failed")


# --------------------------------------------------------------- against the database

PROBE_TABLE = "_reversibility_probe"
assert PROBE_TABLE == "_reversibility_probe"  # every literal below spells it out

_DROP_PROBE = "DROP TABLE IF EXISTS public._reversibility_probe"

IRREVERSIBLE_MIGRATION = '''"""deliberately irreversible; written by this test"""

import sqlalchemy as sa

from alembic import op

revision = "0badc0ffee00"
down_revision = "{down_revision}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("_reversibility_probe", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade() -> None:
    """Drops nothing. The harness must notice."""
'''


def _skip_unless_database() -> str:
    url = settings.test_database_url
    if not url:
        pytest.skip("PREEMPT_TEST_DATABASE_URL unset, so reversibility is UNPROVEN here")
    # Not a skip. Everything below drives this database to `base`.
    if settings.database_url and same_database(settings.database_url, url):
        pytest.fail(
            "PREEMPT_TEST_DATABASE_URL names the same host, port and database as "
            "PREEMPT_DATABASE_URL. This suite runs `alembic downgrade base` against it."
        )
    why = reachable(url)
    if why is not None:
        pytest.skip(
            f"test database unreachable ({why}), so reversibility is UNPROVEN here. "
            "Start it with `docker compose up -d --wait`."
        )
    return url


def _execute(url: str, statement: str) -> None:
    async def _run() -> None:
        engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
        try:
            async with engine.begin() as conn:
                await conn.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.fixture(scope="module", autouse=True)
def _consistent_database() -> None:
    """Establish a real head before any round trip, rather than assuming one.

    An interrupted run leaves `alembic_version` naming a revision whose tables are gone. The
    round trip opens with an unwrapped `downgrade base`, so every later run then died on
    `DROP TABLE price_metric` — "table does not exist" — which says nothing about the actual
    problem. Reproduced by hand: drop the five tables, leave the version row, and the suite
    wedges until someone clears it.

    Cheap because the test database is tmpfs-backed and ephemeral by design. A test that
    assumes its preconditions is a test that fails for reasons unrelated to what it checks.
    """
    if not settings.test_database_url or reachable(settings.test_database_url) is not None:
        return
    _reset_to_head(settings.test_database_url)


@pytest.mark.integration
def test_every_migration_reverses_against_the_real_database() -> None:
    url = _skip_unless_database()
    result = run_round_trip(url, alembic_config())
    assert result.reversible, "\n  ".join(
        ["the round trip did not restore the schema:", *result.differences]
    )


@pytest.mark.integration
def test_the_round_trip_covers_at_least_one_schema_object() -> None:
    """Was a strict xfail until S-010. The baseline created nothing, so the round trip
    proved nothing, and the marker failed the day real tables landed — which is what it was
    for. Deleted rather than kept: the harness now covers actual schema."""
    url = _skip_unless_database()
    covered = run_round_trip(url, alembic_config()).covered
    assert covered >= 1, "the migrations create no schema objects, so the round trip is vacuous"


#: Every table in `public` except alembic's own bookkeeping, read from the catalog rather
#: than hardcoded — a hardcoded list is a second copy of the schema and drifts from it.
#: Tables, not the schema: `DROP SCHEMA public CASCADE` would take timescaledb with it,
#: because the extension is installed into `public` (verified, not assumed).
_DROP_ALL_PUBLIC_TABLES = """
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables
           WHERE schemaname = 'public' AND tablename <> 'alembic_version'
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', t);
  END LOOP;
END $$;
"""


def _reset_to_head(url: str) -> None:
    """Put the database at a real head from any state, without asserting one.

    This replaced `command.stamp(cfg, real_head)`, which was wrong in a way an empty
    baseline could not reveal: stamping *claims* a revision is applied instead of applying
    it. When the sabotage left the database at base, the stamp told alembic S-010's
    migration was in place while its tables were gone, and the next run died on
    `DROP TABLE price_metric` — "table does not exist". Surfaced the moment real schema
    landed, which is the general shape: a cleanup that asserts state is fine until state
    exists.

    Clearing `alembic_version` by SQL rather than stamping also avoids resolving the
    injected revision, which lives only in a `tmp_path` pytest is about to delete.
    """
    _execute(url, _DROP_ALL_PUBLIC_TABLES)
    _execute(url, "DELETE FROM public.alembic_version")
    command.upgrade(alembic_config(), "head")


@pytest.mark.integration
def test_an_irreversible_migration_is_reported(tmp_path: Path) -> None:
    """The failability proof. Without it, every assertion above is satisfied by a harness
    that returns "no differences" unconditionally — the defect this module replaces."""
    url = _skip_unless_database()
    real_head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert real_head is not None, "no migration exists to build an irreversible one on"
    before = snapshot(url)

    (tmp_path / "irreversible.py").write_text(
        IRREVERSIBLE_MIGRATION.format(down_revision=real_head)
    )
    cfg = alembic_config(version_locations=[ALEMBIC_VERSIONS, tmp_path])

    try:
        result = run_round_trip(url, cfg)
        # This line is what makes the two below mean anything. Both of them are satisfied by
        # alembic's DuplicateTableError text alone, so with `snapshot()` gutted the suite was
        # byte-identical to healthy: 8 passed, 1 xfailed. It existed before the trim and was
        # deleted with the machinery around it.
        assert result.covered >= 1, "the injected migration created no schema object to compare"
        assert not result.reversible, "an irreversible migration passed — the harness cannot fail"
        assert any(PROBE_TABLE in line for line in result.differences), (
            f"the harness failed but did not name the table left behind: {result.differences}"
        )
    finally:
        # Not `command.downgrade` — the migration under test is the one that cannot be
        # reversed, so asking it to reverse itself fails exactly when cleanup is needed.
        _execute(url, _DROP_PROBE)
        _reset_to_head(url)

    assert diff(before, snapshot(url)) == [], "the sabotage leaked into the database"


ALEMBIC_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
