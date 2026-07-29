"""Schema snapshots and the migration round trip, as one shared implementation.

`alembic downgrade base && alembic upgrade head` exiting 0 is not evidence of anything.
It is the check that cannot fail: an empty migration reverses perfectly, and so does a
migration that drops nothing. Sprint 0's acceptance criterion asked for exactly that
command and got exactly that non-answer.

What this module does instead is compare the *database* before and after. A migration is
reversible when reversing it leaves the schema indistinguishable from the state before it
was applied — that is a claim about the database, so it is read from the database.

Four things it deliberately does:

- **Steps migration by migration.** Each revision is applied, reversed, and re-applied on
  its own before the whole chain is exercised end to end. A chain-level pass alone is
  satisfied by a migration whose `downgrade()` compensates for damage done by an earlier
  one, and it says nothing about which migration is at fault when it fails.
- **Reports its own coverage.** `RoundTrip.covered` is the number of schema objects the
  migrations actually create. While the baseline is empty that number is zero, and a pass
  therefore proves nothing. Saying so is the honest result; the alternative is a green
  check standing in for a guarantee nobody made.
- **Excludes `alembic_version`.** It is alembic's bookkeeping, not the schema under test,
  and it survives `downgrade base` — comparing it would report a difference on every run
  that has nothing to do with reversibility.
- **Excludes extension-owned objects.** The local image ships timescaledb already
  installed: several thousand catalog tables, functions and types that no migration
  created. Membership is read from `pg_depend`, not guessed from a name prefix, so a
  migration that creates something in a schema an extension happens to own is still seen.
  Extensions themselves are compared by name and version, so a `downgrade` that forgets
  `DROP EXTENSION` is still caught.

WHAT IT DOES NOT SEE. This list is what is known, not a bound, and it is the part of this
file most worth keeping honest — a gap that is queried-but-compared-shallowly is worse
than one that is absent, because a reader concludes it is covered.

- **Row data.** A downgrade that destroys a table's contents while restoring its shape
  reads as reversible. This is correct for *schema* reversibility and wrong for anything
  else, and it is why one of the sabotage cases seeds rows rather than schema.
- **Grants, ownership, comments, publications and subscriptions, event triggers,
  foreign-data wrappers and servers, operator classes, extended statistics objects,
  and default privileges.** None of these are queried.
- **View and routine *text*.** Both are compared by hash, so a change is reported as a
  change but the diff does not show what changed.
- **Anything in a database other than the one it connects to**, and any branch structure
  in the migration chain: `revisions()` walks a linear history.
- **TimescaleDB-specific objects** — hypertables, chunks, continuous aggregates, and
  compression or retention policies. Whether a chunk table carries a `deptype='e'` row in
  `pg_depend`, and is therefore hidden by the extension filter, has not been established.
  It matters from S-010 onward and should be settled before the first hypertable.
"""

from __future__ import annotations

import asyncio
import os
from argparse import Namespace
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

API_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = API_DIR / "alembic.ini"
VERSIONS_DIR = API_DIR / "alembic" / "versions"

# One row per schema object: (class, identity, definition).
#
# Every query carries the same CTE rather than sharing a generated fragment. The
# duplication is deliberate: these are static SQL literals with nothing interpolated into
# them, which is the property that makes them safe to read at a glance.
#
# `ESCAPE '^'` rather than a backslash, because `_timescaledb_catalog` and friends begin
# with LIKE's single-character wildcard and the two escapes are easy to confuse.
#
# Every component of every definition is wrapped in coalesce. `text || NULL` is NULL in
# SQL, so one unguarded NULL erases the whole definition and every object of that class
# compares equal to every other — which is how `pg_get_function_result`, NULL for a
# procedure, once reduced every procedure in the database to the same string.
_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "schema",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname, ''
        FROM pg_namespace n
        WHERE n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_namespace'::regclass AND ext.objid = n.oid
          )
        """,
    ),
    (
        "relation",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || c.relname,
               'kind=' || c.relkind::text
               || ' persistence=' || c.relpersistence::text
               || ' rowsecurity=' || c.relrowsecurity::text
               || ' options=' || coalesce(array_to_string(c.reloptions, ','), '-')
               || ' partition=' || coalesce(pg_get_expr(c.relpartbound, c.oid), '-')
               || ' inherits=' || coalesce((
                      SELECT string_agg(pn.nspname || '.' || pc.relname, ',' ORDER BY pc.relname)
                      FROM pg_inherits inh
                      JOIN pg_class pc ON pc.oid = inh.inhparent
                      JOIN pg_namespace pn ON pn.oid = pc.relnamespace
                      WHERE inh.inhrelid = c.oid
                  ), '-')
               || ' view=' || coalesce(
                      CASE WHEN c.relkind IN ('v', 'm') THEN md5(pg_get_viewdef(c.oid)) END, '-')
               || ' sequence=' || coalesce((
                      SELECT s.seqtypid::regtype::text || ',start=' || s.seqstart
                             || ',increment=' || s.seqincrement || ',min=' || s.seqmin
                             || ',max=' || s.seqmax || ',cache=' || s.seqcache
                             || ',cycle=' || s.seqcycle::text
                      FROM pg_sequence s WHERE s.seqrelid = c.oid
                  ), '-')
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S', 'c')
          AND n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND c.relname = 'alembic_version')
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_class'::regclass AND ext.objid = c.oid
          )
        """,
    ),
    (
        "column",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || c.relname || '.' || a.attname,
               'position=' || a.attnum::text
               || ' type=' || format_type(a.atttypid, a.atttypmod)
               || ' null=' || (NOT a.attnotnull)::text
               || ' default=' || coalesce(pg_get_expr(ad.adbin, ad.adrelid), '-')
               || ' identity=' || coalesce(nullif(a.attidentity::text, ''), '-')
               || ' generated=' || coalesce(nullif(a.attgenerated::text, ''), '-')
               || ' collation=' || coalesce(co.collname, '-')
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        LEFT JOIN pg_collation co ON co.oid = a.attcollation
        WHERE a.attnum > 0
          AND NOT a.attisdropped
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'c')
          AND n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND c.relname = 'alembic_version')
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_class'::regclass AND ext.objid = c.oid
          )
        """,
    ),
    (
        "index",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || ic.relname, pg_get_indexdef(i.indexrelid)
        FROM pg_index i
        JOIN pg_class ic ON ic.oid = i.indexrelid
        JOIN pg_class tc ON tc.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = ic.relnamespace
        WHERE n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND tc.relname = 'alembic_version')
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_class'::regclass AND ext.objid IN (ic.oid, tc.oid)
          )
        """,
    ),
    (
        "constraint",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || tc.relname || '.' || con.conname,
               pg_get_constraintdef(con.oid)
        FROM pg_constraint con
        JOIN pg_class tc ON tc.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = tc.relnamespace
        WHERE n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND tc.relname = 'alembic_version')
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_class'::regclass AND ext.objid = tc.oid
          )
        """,
    ),
    (
        "type",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || t.typname,
               'kind=' || t.typtype::text
               || ' base=' || coalesce(
                      format_type(nullif(t.typbasetype, 0), t.typtypmod), '-')
               || ' notnull=' || t.typnotnull::text
               || ' default=' || coalesce(t.typdefault, '-')
               || ' labels=' || coalesce((
                      SELECT string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)
                      FROM pg_enum e WHERE e.enumtypid = t.oid
                  ), '-')
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typtype IN ('e', 'd', 'c', 'r', 'm')
          AND n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          -- Every table has a composite type of the same name. Standalone composites have
          -- a pg_class row of relkind 'c'; a table's row type does not, and including it
          -- would double every table in the snapshot.
          AND (t.typtype <> 'c' OR EXISTS (
                  SELECT 1 FROM pg_class rc WHERE rc.oid = t.typrelid AND rc.relkind = 'c'))
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_type'::regclass AND ext.objid = t.oid
          )
        """,
    ),
    (
        "collation",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || co.collname,
               'provider=' || co.collprovider::text
               || ' collate=' || coalesce(co.collcollate, '-')
               || ' ctype=' || coalesce(co.collctype, '-')
        FROM pg_collation co
        JOIN pg_namespace n ON n.oid = co.collnamespace
        WHERE n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_collation'::regclass AND ext.objid = co.oid
          )
        """,
    ),
    (
        "routine",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || p.proname
               || '(' || pg_get_function_identity_arguments(p.oid) || ')',
               'kind=' || p.prokind::text
               || ' language=' || l.lanname
               || ' volatility=' || p.provolatile::text
               || ' strict=' || p.proisstrict::text
               || ' security_definer=' || p.prosecdef::text
               || ' returns=' || coalesce(pg_get_function_result(p.oid), '-')
               || ' body=' || md5(coalesce(p.prosrc, ''))
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_language l ON l.oid = p.prolang
        WHERE n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_proc'::regclass AND ext.objid = p.oid
          )
        """,
    ),
    (
        "trigger",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || tc.relname || '.' || tg.tgname,
               pg_get_triggerdef(tg.oid)
        FROM pg_trigger tg
        JOIN pg_class tc ON tc.oid = tg.tgrelid
        JOIN pg_namespace n ON n.oid = tc.relnamespace
        WHERE NOT tg.tgisinternal
          AND n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_trigger'::regclass AND ext.objid = tg.oid
          )
        """,
    ),
    (
        "policy",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || tc.relname || '.' || pol.polname,
               'command=' || pol.polcmd::text
               || ' permissive=' || pol.polpermissive::text
               || ' using=' || coalesce(pg_get_expr(pol.polqual, pol.polrelid), '-')
               || ' check=' || coalesce(pg_get_expr(pol.polwithcheck, pol.polrelid), '-')
        FROM pg_policy pol
        JOIN pg_class tc ON tc.oid = pol.polrelid
        JOIN pg_namespace n ON n.oid = tc.relnamespace
        WHERE n.nspname <> 'information_schema'
          AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT EXISTS (
              SELECT 1 FROM ext
              WHERE ext.classid = 'pg_policy'::regclass AND ext.objid = pol.oid
          )
        """,
    ),
    (
        "extension",
        "SELECT e.extname, e.extversion FROM pg_extension e",
    ),
)

#: Every class the snapshot claims to observe. `test_the_snapshot_sees_every_class_it_claims_to`
#: creates one object of each against a real database, so deleting a query is a red test
#: rather than a silently narrower snapshot.
OBJECT_CLASSES: tuple[str, ...] = tuple(cls for cls, _ in _QUERIES)


@dataclass(frozen=True)
class Snapshot:
    """Every schema object a migration could plausibly have created, sorted."""

    objects: tuple[tuple[str, str, str], ...]

    def __len__(self) -> int:
        return len(self.objects)

    def classes(self) -> set[str]:
        return {cls for cls, _, _ in self.objects}


def diff(before: Snapshot, after: Snapshot) -> list[str]:
    """Human-readable differences, empty when the two schemas are indistinguishable.

    Definitions are compared as well as identities. A downgrade that recreates a table
    with a column made nullable has restored the name and not the schema, and reporting
    only names is how that passes.
    """
    b = {(cls, ident): defn for cls, ident, defn in before.objects}
    a = {(cls, ident): defn for cls, ident, defn in after.objects}

    out: list[str] = []
    out += [f"added {cls} {ident}: {a[cls, ident]}" for cls, ident in sorted(a.keys() - b.keys())]
    out += [f"removed {cls} {ident}: {b[cls, ident]}" for cls, ident in sorted(b.keys() - a.keys())]
    out += [
        f"changed {cls} {ident}: {b[cls, ident]!r} -> {a[cls, ident]!r}"
        for cls, ident in sorted(b.keys() & a.keys())
        if b[cls, ident] != a[cls, ident]
    ]
    return out


async def _read_snapshot(url: str) -> Snapshot:
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        rows: list[tuple[str, str, str]] = []
        async with engine.connect() as conn:
            for cls, sql in _QUERIES:
                result = await conn.execute(text(sql))
                for identity, definition in result:
                    # A NULL here means a `||` chain swallowed one of its components, at
                    # which point every object of this class carries the same definition
                    # and compares equal. Silent in a diff; loud here.
                    if identity is None or definition is None:
                        raise RuntimeError(
                            f"the {cls} query produced a NULL column "
                            f"(identity={identity!r}, definition={definition!r}). "
                            "Some component of the definition is unguarded by coalesce."
                        )
                    rows.append((cls, str(identity), str(definition)))
        return Snapshot(objects=tuple(sorted(rows)))
    finally:
        await engine.dispose()


def snapshot(url: str) -> Snapshot:
    """Read the schema. Synchronous, because alembic's env.py owns its own event loop.

    `env.py` calls `asyncio.run` itself, so anything that drives migrations has to be
    outside a running loop. Making the whole harness synchronous and starting a loop per
    call is the version of that with no hidden interaction.
    """
    return asyncio.run(_read_snapshot(url))


def reachable(url: str) -> str | None:
    """None when the database answers, otherwise why it did not.

    This function decides whether every database-backed test in the suite runs at all, so
    a version of it that always reported "down" would turn the entire integration layer
    into skips and leave the gate green. `test_the_skip_decision_matches_reality` checks
    its verdict against a socket this module opens itself.
    """

    async def _ping() -> None:
        engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(_ping())
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


#: Spellings of "this machine". A URL naming one and a URL naming another point at the
#: same server, and comparing the strings says they do not.
_LOOPBACK = {"", "localhost", "127.0.0.1", "::1"}


def same_database(a: str, b: str) -> bool:
    """True when two URLs name the same host, port and database.

    The `Settings` guard compares two strings, which is not the same question: it passes
    for `localhost` against `127.0.0.1`, for a URL that differs only by `?sslmode=require`,
    and — the case that matters most — it does not run at all when `PREEMPT_DATABASE_URL`
    is unset, which is CI, a fresh clone, and this project's documented state today.
    Credentials are ignored on purpose; two roles on one database are one database.
    """
    left, right = make_url(a), make_url(b)
    host_l = (left.host or "").lower()
    host_r = (right.host or "").lower()
    if host_l != host_r and not (host_l in _LOOPBACK and host_r in _LOOPBACK):
        return False
    return (left.port or 5432) == (right.port or 5432) and left.database == right.database


def alembic_config(version_locations: Sequence[Path] | None = None) -> Config:
    """Alembic pointed at the *test* database, never the application's.

    `-x db=test` is what `env.py` reads to choose `settings.test_database_url`. Passing it
    through `cmd_opts` is the supported programmatic equivalent of the command line.
    It is not on its own a guarantee that the two databases differ — `Settings` compares
    two strings and is inert when `PREEMPT_DATABASE_URL` is unset, so the test module
    checks host, port and database name before driving anything to `base`.
    """
    cfg = Config(str(ALEMBIC_INI), cmd_opts=Namespace(x=["db=test"]))
    if version_locations is not None:
        # `path_separator = os` in alembic.ini, so this list is split on os.pathsep.
        # Joining on a space instead works until a path contains one, which is the kind
        # of defect that appears on someone else's machine and not on this one.
        cfg.set_main_option("version_locations", os.pathsep.join(str(p) for p in version_locations))
    return cfg


def revisions(cfg: Config) -> list[str]:
    """The migration chain, base first. Linear histories only — see the module docstring."""
    script = ScriptDirectory.from_config(cfg)
    return [rev.revision for rev in reversed(list(script.walk_revisions()))]


def _attempt(run: Callable[[], None]) -> str | None:
    # Broad on purpose: a migration that fails is a result this harness reports, not a
    # crash it propagates. Narrowing to the database driver's exceptions would let an
    # error raised inside a `downgrade()` body escape as a test error instead.
    try:
        run()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


@dataclass(frozen=True)
class Step:
    """One migration applied, reversed, and applied again, in isolation."""

    revision: str
    before: Snapshot
    after: Snapshot
    reverted: Snapshot
    reapplied: Snapshot
    reverse_error: str | None = None
    reapply_error: str | None = None

    @property
    def reverse_differences(self) -> list[str]:
        if self.reverse_error is not None:
            return [f"{self.revision}: reversing failed: {self.reverse_error}"]
        return [f"{self.revision}: reversing left {d}" for d in diff(self.before, self.reverted)]

    @property
    def reapply_differences(self) -> list[str]:
        if self.reapply_error is not None:
            return [f"{self.revision}: re-applying failed: {self.reapply_error}"]
        return [
            f"{self.revision}: re-applying produced {d}" for d in diff(self.after, self.reapplied)
        ]

    @property
    def clean(self) -> bool:
        return not self.reverse_differences and not self.reapply_differences


@dataclass(frozen=True)
class RoundTrip:
    """What the harness observed, and how it failed if it did.

    An irreversible migration surfaces in three different ways, and a harness that handles
    only one of them reports the other two as a crash — which reads as "the test is
    broken", not "the migration is". Discovered by writing the sabotage first: the
    empty-`downgrade` case does not produce a difference at all on its own, it produces a
    `DuplicateTableError` when the migration is applied a second time.
    """

    base: Snapshot
    head: Snapshot
    after_reverse: Snapshot
    after_reapply: Snapshot
    steps: tuple[Step, ...] = ()
    #: Revisions never stepped, because an earlier step left the database in a state that
    #: makes every later comparison meaningless.
    unstepped: tuple[str, ...] = ()
    #: False when the chain-level pass was skipped for the same reason.
    chain_ran: bool = True
    reverse_error: str | None = None
    reapply_error: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def covered(self) -> int:
        """Schema objects the migrations create. Zero means the round trip proved nothing."""
        b = {(cls, ident) for cls, ident, _ in self.base.objects}
        h = {(cls, ident) for cls, ident, _ in self.head.objects}
        return len(h - b)

    @property
    def step_reverse_differences(self) -> list[str]:
        return [d for step in self.steps for d in step.reverse_differences]

    @property
    def step_reapply_differences(self) -> list[str]:
        return [d for step in self.steps for d in step.reapply_differences]

    @property
    def reverse_differences(self) -> list[str]:
        """What reversing the whole chain failed to put back — or why it could not."""
        if self.reverse_error is not None:
            return [f"downgrading to base failed: {self.reverse_error}"]
        return diff(self.base, self.after_reverse)

    @property
    def reapply_differences(self) -> list[str]:
        """What re-applying the whole chain produced differently — or why it could not."""
        if self.reapply_error is not None:
            return [f"upgrading to head a second time failed: {self.reapply_error}"]
        return diff(self.head, self.after_reapply)

    @property
    def all_differences(self) -> list[str]:
        return (
            self.step_reverse_differences
            + self.step_reapply_differences
            + self.reverse_differences
            + self.reapply_differences
        )

    @property
    def reversible(self) -> bool:
        return not self.all_differences


def _run_step(url: str, cfg: Config, revision: str, previous: str | None) -> Step:
    before = snapshot(url)
    command.upgrade(cfg, revision)
    after = snapshot(url)
    reverse_error = _attempt(lambda: command.downgrade(cfg, previous or "base"))
    reverted = snapshot(url)
    reapply_error = _attempt(lambda: command.upgrade(cfg, revision))
    reapplied = snapshot(url)
    return Step(
        revision=revision,
        before=before,
        after=after,
        reverted=reverted,
        reapplied=reapplied,
        reverse_error=reverse_error,
        reapply_error=reapply_error,
    )


def run_round_trip(url: str, cfg: Config) -> RoundTrip:
    """Every migration reversed on its own, then the whole chain end to end.

    Starting with a downgrade rather than an upgrade is what makes the result independent
    of whatever the database happened to hold when the run began. Re-applying catches the
    migration that is reversible once and not twice, which a single down-up pass is blind
    to — and it is what catches a `downgrade()` that silently drops nothing, because the
    second `CREATE TABLE` is the thing that objects.

    Stepping stops at the first migration that fails: after that the database no longer
    matches the chain, so every later comparison would report the first failure again
    under a different revision's name. The chain-level pass is skipped for the same
    reason, and both facts are recorded rather than inferred from an empty list.

    The initial `downgrade base` is not wrapped: if the database cannot be brought to base
    in the first place there is no round trip to report on, and the exception is the
    honest answer.
    """
    command.downgrade(cfg, "base")
    base = snapshot(url)

    chain = revisions(cfg)
    steps: list[Step] = []
    unstepped: tuple[str, ...] = ()
    previous: str | None = None
    notes: list[str] = []

    for index, revision in enumerate(chain):
        step = _run_step(url, cfg, revision, previous)
        steps.append(step)
        if not step.clean:
            unstepped = tuple(chain[index + 1 :])
            if unstepped:
                notes.append(
                    f"stopped stepping at {revision}; {len(unstepped)} later migration(s) "
                    "were not checked individually"
                )
            break
        previous = revision

    head = steps[-1].after if steps and not steps[-1].clean else snapshot(url)

    if steps and not steps[-1].clean:
        notes.append("chain-level pass skipped: a migration already failed in isolation")
        return RoundTrip(
            base=base,
            head=head,
            after_reverse=head,
            after_reapply=head,
            steps=tuple(steps),
            unstepped=unstepped,
            chain_ran=False,
            notes=tuple(notes),
        )

    reverse_error = _attempt(lambda: command.downgrade(cfg, "base"))
    after_reverse = snapshot(url)
    reapply_error = _attempt(lambda: command.upgrade(cfg, "head"))
    after_reapply = snapshot(url)

    return RoundTrip(
        base=base,
        head=head,
        after_reverse=after_reverse,
        after_reapply=after_reapply,
        steps=tuple(steps),
        reverse_error=reverse_error,
        reapply_error=reapply_error,
        notes=tuple(notes),
    )
