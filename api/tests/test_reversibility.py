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
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import settings
from app.db import models  # noqa: F401  - registers the tables on Base.metadata
from app.db.base import Base
from tests.reversibility import (
    RoundTrip,
    Snapshot,
    alembic_config,
    diff,
    is_loopback,
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


# `same_database` is what stands between this suite and `downgrade base` against the
# application database. It was deleted by the trim as bloat, restored after review, and
# restored without tests — so it could be reduced to `return False` and nothing complained.


def test_the_same_database_spelled_two_ways_is_detected() -> None:
    assert same_database(
        "postgresql+asyncpg://u:p@localhost:5433/preempt",
        "postgresql+asyncpg://other:pw@127.0.0.1:5433/preempt?ssl=require",
    )


def test_different_ports_are_different_databases() -> None:
    assert not same_database(
        "postgresql+asyncpg://u:p@localhost:5433/preempt",
        "postgresql+asyncpg://u:p@localhost:5434/preempt",
    )


def test_different_names_on_one_server_are_different_databases() -> None:
    assert not same_database(
        "postgresql+asyncpg://u:p@localhost:5433/preempt",
        "postgresql+asyncpg://u:p@localhost:5433/preempt_test",
    )


def test_a_remote_host_is_not_loopback() -> None:
    """The guard for the unset case. `example.com` rather than a provider hostname: the
    gate's secret scanner flags a password against a host with a letter and a dot, and it
    cannot tell a convincing placeholder from a credential."""
    assert is_loopback("postgresql+asyncpg://user:password@127.0.0.1:5434/t")
    assert is_loopback("postgresql+asyncpg://user:password@localhost:5434/t")
    assert not is_loopback("postgresql+asyncpg://user:password@ep-x.example.com:5432/t")


# --------------------------------------------------------------- against the database

ALEMBIC_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

PROBE_TABLE = "_reversibility_probe"
assert PROBE_TABLE == "_reversibility_probe"  # every literal below spells it out

_DROP_PROBE = "DROP TABLE IF EXISTS public._reversibility_probe"

FAILING_UPGRADE_MIGRATION = '''"""upgrade raises; written by this test"""

from alembic import op  # noqa: F401

revision = "0badc0ffee01"
down_revision = "{down_revision}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    raise RuntimeError("this migration cannot be applied")


def downgrade() -> None:
    """Never reached."""
'''

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
    # Not a skip. Everything below drives this database to `base`, which destroys it.
    #
    # Two cases, because the interesting one has no second URL to compare against. When
    # PREEMPT_DATABASE_URL is set, the two must not name the same database. When it is unset
    # — CI by design, and every fresh clone — there is nothing to compare, so the target must
    # at least be this machine. A remote host as the test database with no application URL to
    # check it against is the shape that gets someone's real database dropped.
    #
    # The `settings.database_url and ...` version of this check was the same hole one layer
    # up: the guard simply did not run in the unset case, which is the case that matters.
    if settings.database_url:
        if same_database(settings.database_url, url):
            pytest.fail(
                "PREEMPT_TEST_DATABASE_URL names the same host, port and database as "
                "PREEMPT_DATABASE_URL. This suite runs `alembic downgrade base` against it."
            )
    elif not is_loopback(url):
        pytest.fail(
            f"PREEMPT_TEST_DATABASE_URL points at a remote host ({make_url(url).host}) and "
            "PREEMPT_DATABASE_URL is unset, so nothing can prove they differ. This suite "
            "runs `alembic downgrade base` against it. Point it at a local database."
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
    """Was a strict xfail until S-010. The baseline created nothing, so the round trip proved
    nothing, and the marker failed the day real tables landed — which is what it was for.

    Deleting it broke a pin, and this is the repair. The xfail had required `covered == 0`
    for the real baseline while the sabotage required `>= 1`; no constant satisfied both.
    With the xfail gone both wanted `>= 1`, so `covered` could return a constant 1 and the
    suite stayed green — the vacuity the whole module exists to prevent, reintroduced by
    removing its counterweight. The bound below is derived from the models rather than
    hardcoded, so it grows with the schema instead of drifting from it.
    """
    url = _skip_unless_database()
    result = run_round_trip(url, alembic_config())

    # Every table contributes at least one relation and one column, so twice the table count
    # is a floor no constant survives.
    floor = 2 * len(Base.metadata.tables)
    assert result.covered >= floor, (
        f"the migrations created {result.covered} schema objects; {len(Base.metadata.tables)} "
        f"tables should produce at least {floor}. Either the schema did not apply, or "
        "`covered` is not counting."
    )

    # And that every class the snapshot claims is actually read. `covered >= n` is satisfied
    # by one query returning enough rows: cutting `_QUERIES` to a single class left the suite
    # green. Real schema provides all four, so this needs no fixture.
    assert result.head_classes == {"relation", "column", "index", "constraint"}, (
        f"the snapshot read only {sorted(result.head_classes)} from a schema that has all "
        "four classes — a query has been dropped from `_QUERIES`"
    )


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
def test_a_migration_that_will_not_apply_is_reported(tmp_path: Path) -> None:
    """The forward `upgrade` must be a reported result, not an escaping exception.

    `_attempt`'s own comment says a failing migration is "a result to report, not a crash to
    propagate", but the forward upgrade was left unwrapped, and reverting the wrap left the
    suite green — so the fix was one rewrite from vanishing, which is the mechanism that has
    already cost this file three defects.
    """
    url = _skip_unless_database()
    real_head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert real_head is not None
    (tmp_path / "failing.py").write_text(FAILING_UPGRADE_MIGRATION.format(down_revision=real_head))
    cfg = alembic_config(version_locations=[ALEMBIC_VERSIONS, tmp_path])

    try:
        result = run_round_trip(url, cfg)
        assert not result.reversible
        assert result.differences[0].startswith("upgrading to head failed:"), (
            f"a migration that raises on upgrade was not reported as such: {result.differences}"
        )
        assert "cannot be applied" in result.differences[0]
    finally:
        _reset_to_head(url)


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
        assert result.covered >= 1, (
            "the injected migration created no schema object to compare. If the forward "
            f"upgrade failed, the real error is here: {result.differences}"
        )
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
