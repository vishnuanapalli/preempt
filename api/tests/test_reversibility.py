"""Migrations are reversible — and this is the check that can say otherwise.

S-002 originally asked for `alembic downgrade base` then `upgrade head` to succeed. That
exits 0 against a migration whose `upgrade()` and `downgrade()` are both `pass`, which is
exactly what this project's baseline is, and it was reported as demo evidence. So the useful
question is not "are the migrations reversible" but "would this notice if they were not".

Four differ tests need no database. Two run against the real test database: the round trip,
and one deliberately irreversible migration that must be reported as such — a check nobody
has watched fail is indistinguishable from one that cannot.

Nothing here proves the migrations are reversible *yet*: the baseline creates no schema
objects, so `covered` is 0. The strict xfail says so and fails the day S-010 adds a table,
which is the day to delete it.

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


@pytest.mark.integration
def test_every_migration_reverses_against_the_real_database() -> None:
    url = _skip_unless_database()
    result = run_round_trip(url, alembic_config())
    assert result.reversible, "\n  ".join(
        ["the round trip did not restore the schema:", *result.differences]
    )


@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "the baseline creates no schema objects, so the round trip covers nothing and proves "
        "nothing (S-002, D-015). Strict: the day S-010 adds a table this fails, and deleting "
        "the marker is the fix."
    ),
    raises=AssertionError,
    strict=True,
)
def test_the_round_trip_covers_at_least_one_schema_object() -> None:
    url = _skip_unless_database()
    assert run_round_trip(url, alembic_config()).covered >= 1


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
        assert not result.reversible, "an irreversible migration passed — the harness cannot fail"
        assert any(PROBE_TABLE in line for line in result.differences), (
            f"the harness failed but did not name the table left behind: {result.differences}"
        )
    finally:
        # Not `command.downgrade` — the migration under test is the one that cannot be
        # reversed, so asking it to reverse itself fails exactly when cleanup is needed.
        command.stamp(cfg, real_head)
        _execute(url, _DROP_PROBE)

    assert diff(before, snapshot(url)) == [], "the sabotage leaked into the database"


ALEMBIC_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
