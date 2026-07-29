"""Migrations are reversible — and this is the check that can say otherwise.

S-002 originally asked for `alembic downgrade base` followed by `upgrade head` to
succeed. That command exits 0 against a migration whose `upgrade()` and `downgrade()` are
both `pass`, which is exactly what this project's baseline is. The criterion was therefore
satisfied by a migration that does nothing, and the round trip was reported as evidence.

So the useful question is not "are the migrations reversible" but "would this check
notice if they were not". Everything below exists to answer the second one:

- the differ and the URL comparison are exercised without a database, so their ability to
  report a difference is established even where no database exists;
- the round trip runs against the real test database, migration by migration;
- one test creates an object of every class the snapshot claims to observe, so a query
  quietly deleted from `_QUERIES` is a red test rather than a narrower snapshot;
- one test checks the skip decision against a socket, because `reachable()` returning
  "down" would turn this whole layer into skips and leave the gate green;
- and three tests deliberately introduce irreversible migrations, one per failure path,
  and fail if the harness reports them as fine.

What none of it proves today: the baseline creates no schema objects, so the round trip
covers nothing. `test_the_round_trip_covers_at_least_one_schema_object` is marked strict
xfail for precisely that reason and will *fail* the day Sprint 1 adds a table — which is
the day the marker should be deleted, and a failing gate is what makes that happen.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import settings
from tests.reversibility import (
    OBJECT_CLASSES,
    VERSIONS_DIR,
    RoundTrip,
    Snapshot,
    Step,
    alembic_config,
    diff,
    reachable,
    revisions,
    run_round_trip,
    same_database,
    snapshot,
)

# ----------------------------------------------------------------- no database needed

#: Written out rather than derived from `_QUERIES`. Deriving it would make the coverage
#: test pass by construction: delete a query, the expectation shrinks with it, and the
#: snapshot silently stops observing a whole class of schema object.
EXPECTED_CLASSES = {
    "schema",
    "relation",
    "column",
    "index",
    "constraint",
    "type",
    "collation",
    "routine",
    "trigger",
    "policy",
    "extension",
}


def _snap(*objects: tuple[str, str, str]) -> Snapshot:
    return Snapshot(objects=tuple(sorted(objects)))


def test_the_snapshot_declares_every_class_this_suite_pins() -> None:
    assert set(OBJECT_CLASSES) == EXPECTED_CLASSES, (
        "the snapshot's query list and this suite's expectation have drifted; a class "
        "added to one and not the other is a class nothing checks"
    )


def test_identical_schemas_report_no_difference() -> None:
    s = _snap(("relation", "public.pool", "kind=r"), ("column", "public.pool.id", "type=integer"))
    assert diff(s, s) == []


def test_a_table_left_behind_is_reported() -> None:
    """The failure an empty downgrade produces: the upgrade's table is still there."""
    before = _snap(("relation", "public.alembic_only", "kind=r"))
    after = _snap(
        ("relation", "public.alembic_only", "kind=r"), ("relation", "public.pool", "kind=r")
    )
    assert diff(before, after) == ["added relation public.pool: kind=r"]


def test_a_table_not_recreated_is_reported() -> None:
    before = _snap(("relation", "public.pool", "kind=r"))
    assert diff(before, _snap()) == ["removed relation public.pool: kind=r"]


def test_a_column_restored_with_a_different_shape_is_reported() -> None:
    """Name-only comparison is how a nullability change survives a round trip unnoticed."""
    before = _snap(("column", "public.pool.price", "type=numeric null=false"))
    after = _snap(("column", "public.pool.price", "type=numeric null=true"))
    assert len(diff(before, after)) == 1
    assert diff(before, after)[0].startswith("changed column public.pool.price:")


def _round_trip(base: Snapshot, head: Snapshot, **kwargs: object) -> RoundTrip:
    defaults: dict[str, object] = {"after_reverse": base, "after_reapply": head}
    defaults.update(kwargs)
    return RoundTrip(base=base, head=head, **defaults)  # type: ignore[arg-type]


def test_coverage_counts_only_what_the_migrations_add() -> None:
    base = _snap(("extension", "timescaledb", "2.24.0"))
    head = _snap(("extension", "timescaledb", "2.24.0"), ("relation", "public.pool", "kind=r"))
    rt = _round_trip(base, head)
    assert rt.covered == 1
    assert rt.reversible


def test_coverage_is_zero_when_the_migrations_create_nothing() -> None:
    """Today's real answer, and the one a constant cannot fake. Asserting only the
    non-zero case lets `covered` return 1 unconditionally and still pass."""
    base = _snap(("extension", "timescaledb", "2.24.0"))
    assert _round_trip(base, base).covered == 0


def test_coverage_counts_every_object_not_just_the_first() -> None:
    base = _snap()
    head = _snap(
        ("relation", "public.pool", "kind=r"),
        ("column", "public.pool.id", "type=integer"),
        ("index", "public.pool_pkey", "CREATE UNIQUE INDEX ..."),
    )
    assert _round_trip(base, head).covered == 3


def test_a_round_trip_that_did_not_restore_the_schema_is_not_reversible() -> None:
    """The harness's own verdict, checked directly. If this can pass while
    `after_reverse` differs from `base`, nothing below it means anything."""
    base = _snap()
    head = _snap(("relation", "public.pool", "kind=r"))
    rt = _round_trip(base, head, after_reverse=head)
    assert not rt.reversible
    assert rt.reverse_differences == ["added relation public.pool: kind=r"]


def test_a_migration_that_is_reversible_once_and_not_twice_is_caught() -> None:
    """Re-applying is checked too: this one comes back up missing its index."""
    base = _snap()
    head = _snap(
        ("relation", "public.pool", "kind=r"), ("index", "public.ix_pool", "CREATE INDEX ...")
    )
    rt = _round_trip(base, head, after_reapply=_snap(("relation", "public.pool", "kind=r")))
    assert not rt.reversible
    assert rt.reverse_differences == []
    assert rt.reapply_differences == ["removed index public.ix_pool: CREATE INDEX ..."]


def test_a_downgrade_that_raises_is_not_reversible() -> None:
    """The loud shape. Schema comparison alone would call this reversible: the downgrade
    stopped before changing anything, so nothing differs."""
    base = _snap(("relation", "public.pool", "kind=r"))
    rt = _round_trip(base, base, reverse_error="NotImplementedError: cannot be reversed")
    assert not rt.reversible
    assert rt.reverse_differences == [
        "downgrading to base failed: NotImplementedError: cannot be reversed"
    ]


def test_a_re_application_that_fails_is_not_reversible() -> None:
    """What an empty `downgrade()` actually produces: the second upgrade hits its own table."""
    base = _snap()
    head = _snap(("relation", "public.pool", "kind=r"))
    rt = _round_trip(
        base,
        head,
        after_reverse=head,
        reapply_error='DuplicateTableError: relation "pool" already exists',
    )
    assert not rt.reversible
    assert rt.reapply_differences == [
        "upgrading to head a second time failed: "
        'DuplicateTableError: relation "pool" already exists'
    ]


def _step(**kwargs: object) -> Step:
    empty = _snap()
    defaults: dict[str, object] = {
        "revision": "abc123",
        "before": empty,
        "after": empty,
        "reverted": empty,
        "reapplied": empty,
    }
    defaults.update(kwargs)
    return Step(**defaults)  # type: ignore[arg-type]


def test_a_single_migration_that_does_not_reverse_is_named_by_its_revision() -> None:
    """A chain-level verdict says the chain is broken; this says which migration broke it."""
    step = _step(reverted=_snap(("relation", "public.pool", "kind=r")))
    assert not step.clean
    assert step.reverse_differences == ["abc123: reversing left added relation public.pool: kind=r"]


def test_a_failing_step_makes_the_whole_round_trip_not_reversible() -> None:
    """Without this, `reversible` could ignore the per-migration pass entirely."""
    base = _snap()
    rt = _round_trip(base, base, steps=(_step(reverse_error="NotImplementedError: no"),))
    assert not rt.reversible
    assert rt.step_reverse_differences == ["abc123: reversing failed: NotImplementedError: no"]


# `same_database` is what stands between this harness and `downgrade base` against the
# application database. The `Settings` guard is not that: it compares two strings, and is
# inert whenever PREEMPT_DATABASE_URL is unset — CI, a fresh clone, and the documented
# owner-blocked state today.
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


def test_different_hosts_are_different_databases() -> None:
    """The remote host is `example.com`, not a provider hostname.

    Section 2 of the gate flags any tracked line carrying a password against a host that
    has a letter and a dot — which a realistic-looking `ep-x.<provider>.tech` URL does,
    and which turned the gate red on the first run after this test was written. Real
    credentials and convincing placeholders are indistinguishable to a scanner, and the
    scanner is right to refuse to tell them apart.
    """
    assert not same_database(
        "postgresql+asyncpg://u:p@localhost:5433/preempt",
        "postgresql+asyncpg://user:password@ep-x.example.com:5433/preempt",
    )


# ------------------------------------------------------------ against a real database

PROBE_TABLE = "_reversibility_probe"
PROBE_REVISION = "0badc0ffee00"
PROBE_SCHEMA = "_reversibility_classes"

# Every literal below spells these out. Interpolating an identifier into SQL is a habit
# worth not having even where it is a module constant, and an exact-equality assert on the
# constant covers every one of those literals at once — a substring check does not.
assert PROBE_TABLE == "_reversibility_probe"
assert PROBE_SCHEMA == "_reversibility_classes"

_CREATE_PROBE = "CREATE TABLE IF NOT EXISTS public._reversibility_probe (id integer primary key)"
_DROP_PROBE = "DROP TABLE IF EXISTS public._reversibility_probe"

# One object of every class the snapshot claims to observe. `extension` is the exception:
# timescaledb is installed by the compose image, so that class is non-empty already.
_CREATE_EVERY_CLASS = (
    "CREATE SCHEMA _reversibility_classes",
    "CREATE TYPE _reversibility_classes.state AS ENUM ('ok', 'bad')",
    'CREATE COLLATION _reversibility_classes.plain FROM "C"',
    "CREATE TABLE _reversibility_classes.thing ("
    "  id integer PRIMARY KEY,"
    "  state _reversibility_classes.state NOT NULL,"
    "  label text COLLATE _reversibility_classes.plain)",
    "CREATE INDEX ix_thing_state ON _reversibility_classes.thing (state)",
    "CREATE VIEW _reversibility_classes.thing_v AS SELECT id FROM _reversibility_classes.thing",
    "CREATE SEQUENCE _reversibility_classes.counter",
    "CREATE FUNCTION _reversibility_classes.touch() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN RETURN NEW; END $$",
    "CREATE TRIGGER thing_touch BEFORE INSERT ON _reversibility_classes.thing "
    "FOR EACH ROW EXECUTE FUNCTION _reversibility_classes.touch()",
    "ALTER TABLE _reversibility_classes.thing ENABLE ROW LEVEL SECURITY",
    "CREATE POLICY thing_all ON _reversibility_classes.thing USING (true)",
)
_DROP_EVERY_CLASS = "DROP SCHEMA IF EXISTS _reversibility_classes CASCADE"

IRREVERSIBLE_MIGRATION = '''"""deliberately irreversible; written by the harness's own test"""

import sqlalchemy as sa

from alembic import op

revision = "{revision}"
down_revision = "{down_revision}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    {upgrade}


def downgrade() -> None:
    {downgrade}
'''


@dataclass(frozen=True)
class Sabotage:
    """One deliberately irreversible migration, and what the harness must say about it."""

    upgrade: str
    downgrade: str
    #: Substring the harness's report must contain. Asserting only that *something* failed
    #: passes on a harness that reports the wrong reason, and a check that cannot tell you
    #: which failure it found is a check you cannot act on.
    evidence: str
    #: True when the table exists before the migrations run, so the migration changes rows
    #: rather than schema.
    seeded: bool = False
    #: True when the reverse is genuinely clean and only re-application catches it.
    only_reapply_catches_it: bool = False


# Three ways a migration is irreversible, because they fail through three different paths
# and a harness that catches one can be blind to the others.
SABOTAGE = {
    # The dangerous shape: nothing raises during the downgrade at all.
    "silently drops nothing": Sabotage(
        upgrade='op.create_table("_reversibility_probe", sa.Column("id", sa.Integer(), '
        "primary_key=True))",
        downgrade='"""Drops nothing, raises nothing."""',
        evidence=PROBE_TABLE,
    ),
    "raises on downgrade": Sabotage(
        upgrade='op.create_table("_reversibility_probe", sa.Column("id", sa.Integer(), '
        "primary_key=True))",
        downgrade='raise NotImplementedError("this migration cannot be reversed")',
        evidence="NotImplementedError",
    ),
    # Seeding a table that already exists is a real migration pattern, and it is the one
    # shape whose residue this harness cannot see: rows are not schema, so the reverse
    # looks perfect. Only applying the migration a second time finds it. Without this
    # case, removing the re-application step entirely leaves the suite green — which was
    # true when it was written, and is how an unpinned mechanism survives a review.
    "leaves rows the second apply collides with": Sabotage(
        upgrade='op.execute("INSERT INTO public._reversibility_probe (id) VALUES (1)")',
        downgrade='"""Leaves the row behind. Invisible to a schema comparison."""',
        evidence="IntegrityError",
        seeded=True,
        only_reapply_catches_it=True,
    ),
}


def _skip_unless_database() -> str:
    url = settings.test_database_url
    if not url:
        pytest.skip(
            "PREEMPT_TEST_DATABASE_URL is unset, so migration reversibility is UNPROVEN here. "
            "It is proven only where a database runs: `docker compose up -d --wait`."
        )
    # Not a skip. Everything below drives this database to `base`; if it is the
    # application's, that destroys it. `Settings` compares two strings and is inert when
    # PREEMPT_DATABASE_URL is unset, so the real comparison happens here.
    if settings.database_url and same_database(settings.database_url, url):
        pytest.fail(
            "PREEMPT_TEST_DATABASE_URL names the same host, port and database as "
            "PREEMPT_DATABASE_URL. This suite runs `alembic downgrade base` against it."
        )
    why = reachable(url)
    if why is not None:
        pytest.skip(
            f"test database unreachable ({why}), so migration reversibility is UNPROVEN here. "
            "Start it with `docker compose up -d --wait`."
        )
    return url


@pytest.mark.integration
def test_the_skip_decision_matches_reality() -> None:
    """`reachable()` is the harness's off switch, so its verdict is checked independently.

    Replacing its body with a constant "down" removes every database-backed test in this
    module and leaves `./scripts/verify.sh` green — the skips print, but printing is not
    failing. A socket opened here shares no code with it.
    """
    url = settings.test_database_url
    if not url:
        pytest.skip("PREEMPT_TEST_DATABASE_URL is unset; there is no verdict to check")

    parsed = make_url(url)
    host, port = parsed.host or "localhost", parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=5):
            listening = True
    except OSError:
        listening = False

    if not listening:
        pytest.skip(f"nothing is listening on {host}:{port}, so a 'down' verdict agrees")

    assert reachable(url) is None, (
        f"something is listening on {host}:{port} but `reachable` reports "
        f"{reachable(url)!r}. Either the harness's off switch is broken — in which case "
        "every integration test in this module is silently skipping — or the database is "
        "up but refusing this connection."
    )


@pytest.mark.integration
def test_the_snapshot_sees_every_class_it_claims_to() -> None:
    """One object of each class, so a deleted query is a red test.

    Six of the eight original classes were exercised by nothing: every unit test builds
    snapshots by hand, and the sabotage migrations only ever create a plain table. Cutting
    `_QUERIES` down to relations and columns produced byte-identical output.
    """
    url = _skip_unless_database()
    try:
        _execute(url, _DROP_EVERY_CLASS)
        for statement in _CREATE_EVERY_CLASS:
            _execute(url, statement)
        observed = snapshot(url)
    finally:
        _execute(url, _DROP_EVERY_CLASS)

    missing = EXPECTED_CLASSES - observed.classes()
    assert not missing, (
        f"the snapshot observed nothing of class {sorted(missing)} even though an object of "
        "each was created. A query is missing from `_QUERIES`, or its filters exclude what "
        "it is supposed to see. ('extension' relies on timescaledb being installed by the "
        "compose image.)"
    )

    # `text || NULL` is NULL, so one unguarded component erases a whole definition and
    # `str(None)` stores it as this exact string. Every object of that class then compares
    # equal to every other and the diff goes quiet. The harness raises on a NULL column;
    # this is the symptom, checked separately, because a guard and the thing it guards
    # against should not be pinned by the same assertion.
    collapsed = [(cls, ident) for cls, ident, defn in observed.objects if defn == "None"]
    assert not collapsed, (
        f"{len(collapsed)} definitions collapsed to the string 'None', starting with "
        f"{collapsed[:3]}. Some component of that class's definition is unguarded by "
        "coalesce, and every object of the class now compares equal."
    )

    # The three relation kinds must be distinguishable from one another. A definition that
    # carries only `relkind` would satisfy the class check above while reporting a view
    # whose body changed, or a sequence whose increment changed, as unchanged.
    definitions = {
        ident: defn
        for cls, ident, defn in observed.objects
        if cls == "relation" and ident.startswith(f"{PROBE_SCHEMA}.")
    }
    assert len(set(definitions.values())) == len(definitions), (
        f"a table, a view and a sequence do not have distinct definitions: {definitions}"
    )


@pytest.fixture(scope="module")
def round_trip() -> RoundTrip:
    """One round trip shared by the tests that read it, rather than one each."""
    url = _skip_unless_database()
    return run_round_trip(url, alembic_config())


@pytest.mark.integration
def test_the_harness_stepped_every_migration(round_trip: RoundTrip) -> None:
    """Every assertion about steps is vacuous if there are no steps."""
    expected = revisions(alembic_config())
    assert [step.revision for step in round_trip.steps] == expected
    assert round_trip.unstepped == ()
    assert round_trip.chain_ran


@pytest.mark.integration
def test_every_migration_reverses_to_the_schema_that_preceded_it(round_trip: RoundTrip) -> None:
    """Per migration, not per chain. A chain-level pass is satisfied by a downgrade that
    compensates for damage an earlier migration did."""
    assert round_trip.step_reverse_differences == [], "\n  ".join(
        [
            "a migration did not reverse to the schema before it:",
            *round_trip.step_reverse_differences,
        ]
    )


@pytest.mark.integration
def test_every_migration_can_be_applied_twice(round_trip: RoundTrip) -> None:
    assert round_trip.step_reapply_differences == [], "\n  ".join(
        ["a migration did not survive being applied again:", *round_trip.step_reapply_differences]
    )


@pytest.mark.integration
def test_the_whole_chain_reverses_to_the_schema_that_preceded_it(round_trip: RoundTrip) -> None:
    assert round_trip.reverse_differences == [], "\n  ".join(
        ["downgrading to base did not restore the schema:", *round_trip.reverse_differences]
    )


@pytest.mark.integration
def test_re_applying_the_whole_chain_produces_the_same_schema(round_trip: RoundTrip) -> None:
    assert round_trip.reapply_differences == [], "\n  ".join(
        ["upgrading to head a second time differed:", *round_trip.reapply_differences]
    )


@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "the baseline migration creates no schema objects, so the round trip above covers "
        "nothing and proves nothing (S-002, D-015). Strict: the day Sprint 1 adds a table "
        "this fails, and deleting the marker is the fix."
    ),
    raises=AssertionError,
    strict=True,
)
def test_the_round_trip_covers_at_least_one_schema_object(round_trip: RoundTrip) -> None:
    assert round_trip.covered >= 1


@pytest.mark.integration
@pytest.mark.parametrize("shape", sorted(SABOTAGE))
def test_the_harness_reports_an_irreversible_migration(shape: str, tmp_path: Path) -> None:
    """The failability proof, run against every shape of irreversible migration.

    Without this, every assertion above is satisfied by a harness that returns "no
    differences" unconditionally — which is the defect this whole module replaces. Three
    shapes rather than one because they fail through three different code paths: the
    silent one is caught by the schema comparison, the loud one by the downgrade itself,
    and the seeded one only by applying the migrations a second time.
    """
    url = _skip_unless_database()
    real_head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert real_head is not None, "no migrations exist to build an irreversible one on top of"
    sabotage = SABOTAGE[shape]

    # Taken before the seed table exists, so cleanup can drop it unconditionally on every
    # failure path. Dropping it only on the success path leaked it into the next case,
    # where it crashed the failability proof itself.
    before = snapshot(url)
    if sabotage.seeded:
        _execute(url, _CREATE_PROBE)

    (tmp_path / "irreversible.py").write_text(
        IRREVERSIBLE_MIGRATION.format(
            revision=PROBE_REVISION,
            down_revision=real_head,
            upgrade=sabotage.upgrade,
            downgrade=sabotage.downgrade,
        )
    )
    cfg = alembic_config(version_locations=[VERSIONS_DIR, tmp_path])

    try:
        result = run_round_trip(url, cfg)

        assert not result.reversible, (
            f"an irreversible migration ({shape}) passed the round trip — the harness cannot fail"
        )
        assert any(sabotage.evidence in line for line in result.all_differences), (
            f"the harness failed, but not for the reason it should have. Expected a line "
            f"mentioning {sabotage.evidence!r}; got {result.all_differences}"
        )
        assert any(PROBE_REVISION in line for line in result.all_differences), (
            f"the report does not name the migration at fault: {result.all_differences}"
        )
        if sabotage.only_reapply_catches_it:
            assert result.step_reverse_differences == [], (
                "this shape is meant to be invisible to the schema comparison; if the "
                f"reverse now reports {result.step_reverse_differences} it is no longer "
                "pinning the re-application step"
            )
            assert result.covered == 0, "a row-only migration must not register as coverage"
        else:
            assert result.covered >= 1, "the injected migration created nothing to reverse"
    finally:
        _restore(url, cfg, real_head)

    # The sabotage must not leak into the tests that run after it.
    assert diff(before, snapshot(url)) == []


def _restore(url: str, cfg: Config, real_head: str) -> None:
    """Put the database back on the real head, whatever state the sabotage left it in.

    Deliberately not `command.downgrade` — the migration under test is the one that
    cannot be reversed, so asking it to reverse itself is how cleanup fails exactly when
    it is needed. Stamping and dropping is state this test knows to be true: the probe is
    the only thing the injected migration touched, and every real migration is still
    applied.

    Stamp first. If the drop raises and the stamp has not run, the database is left on a
    revision that exists only in a `tmp_path` pytest is about to delete, and every later
    run fails on the unwrapped `downgrade` that opens the round trip.
    """
    command.stamp(cfg, real_head)
    _execute(url, _DROP_PROBE)


def _execute(url: str, statement: str) -> None:
    async def _run() -> None:
        engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
        try:
            async with engine.begin() as conn:
                await conn.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(_run())
