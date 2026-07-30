"""Are the migrations reversible? Read from the database, not from an exit code.

`alembic downgrade base && alembic upgrade head` exiting 0 proves nothing: an empty
migration reverses perfectly, and this project's only migration has `pass` for both
directions. S-002's original criterion was satisfied by exactly that. So this compares the
*schema* before and after — reversible means reversing leaves the database
indistinguishable from before it was applied.

Four object classes — relations, columns, indexes, constraints — because those are what a
migration creates. `alembic_version` and extension-owned objects are excluded for
correctness: the first survives `downgrade base`, and the local image ships timescaledb.

Not seen: row data, grants, ownership, triggers, policies, types, routines, view and
sequence internals, TimescaleDB objects. A downgrade that destroys a table's contents while
restoring its shape reads as reversible here. Trimmed from 667 lines on 2026-07-29 — see
`22d656b` and ledger R9/R10.
"""

from __future__ import annotations

import asyncio
import os
from argparse import Namespace
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

# Every definition component is coalesce-wrapped: `text || NULL` is NULL in SQL, so one
# unguarded component erases a whole definition and every object of that class then
# compares equal to every other. `_read_snapshot` raises rather than store it.
_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "relation",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || c.relname, 'kind=' || c.relkind::text
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S')
          AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND c.relname = 'alembic_version')
          AND NOT EXISTS (SELECT 1 FROM ext
                          WHERE ext.classid = 'pg_class'::regclass AND ext.objid = c.oid)
        """,
    ),
    (
        "column",
        """
        WITH ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
        SELECT n.nspname || '.' || c.relname || '.' || a.attname,
               'type=' || format_type(a.atttypid, a.atttypmod)
               || ' null=' || (NOT a.attnotnull)::text
               || ' default=' || coalesce(pg_get_expr(ad.adbin, ad.adrelid), '-')
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r', 'p', 'v', 'm')
          AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND c.relname = 'alembic_version')
          AND NOT EXISTS (SELECT 1 FROM ext
                          WHERE ext.classid = 'pg_class'::regclass AND ext.objid = c.oid)
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
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND tc.relname = 'alembic_version')
          AND NOT EXISTS (SELECT 1 FROM ext WHERE ext.classid = 'pg_class'::regclass
                          AND ext.objid IN (ic.oid, tc.oid))
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
        WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg^_%' ESCAPE '^'
          AND NOT (n.nspname = 'public' AND tc.relname = 'alembic_version')
          AND NOT EXISTS (SELECT 1 FROM ext
                          WHERE ext.classid = 'pg_class'::regclass AND ext.objid = tc.oid)
        """,
    ),
)


@dataclass(frozen=True)
class Snapshot:
    objects: tuple[tuple[str, str, str], ...]


def diff(before: Snapshot, after: Snapshot) -> list[str]:
    """Differences, empty when the two schemas are indistinguishable.

    Definitions are compared as well as names: a downgrade that recreates a table with a
    column made nullable has restored the name and not the schema.
    """
    b = {(cls, ident): defn for cls, ident, defn in before.objects}
    a = {(cls, ident): defn for cls, ident, defn in after.objects}
    out = [f"added {c} {i}: {a[c, i]}" for c, i in sorted(a.keys() - b.keys())]
    out += [f"removed {c} {i}: {b[c, i]}" for c, i in sorted(b.keys() - a.keys())]
    out += [
        f"changed {c} {i}: {b[c, i]!r} -> {a[c, i]!r}"
        for c, i in sorted(b.keys() & a.keys())
        if b[c, i] != a[c, i]
    ]
    return out


async def _read_snapshot(url: str) -> Snapshot:
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        rows: list[tuple[str, str, str]] = []
        async with engine.connect() as conn:
            for cls, sql in _QUERIES:
                for identity, definition in await conn.execute(text(sql)):
                    if identity is None or definition is None:
                        raise RuntimeError(
                            f"the {cls} query produced a NULL column; a definition "
                            "component is unguarded by coalesce"
                        )
                    rows.append((cls, str(identity), str(definition)))
        return Snapshot(objects=tuple(sorted(rows)))
    finally:
        await engine.dispose()


def snapshot(url: str) -> Snapshot:
    """Synchronous, because alembic's env.py calls `asyncio.run` itself."""
    return asyncio.run(_read_snapshot(url))


def reachable(url: str) -> str | None:
    """None when the database answers, otherwise why it did not."""

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


#: Spellings of "this machine". Two URLs naming different ones point at the same server.
_LOOPBACK = {"", "localhost", "127.0.0.1", "::1"}


def is_loopback(url: str) -> bool:
    """True when the URL names this machine. Used where there is no second URL to compare."""
    return (make_url(url).host or "").lower() in _LOOPBACK


def same_database(a: str, b: str) -> bool:
    """True when two URLs name the same host, port and database.

    Restored 2026-07-29 after the trim deleted it as bloat. It is not bloat: it guards live
    code. `Settings` compares two strings, so it passes for `localhost` against `127.0.0.1`
    or a differing query string, and it does not run at all when PREEMPT_DATABASE_URL is
    unset. Everything here drives a database to `base`; against the application database
    that destroys it. Credentials are ignored — two roles on one database are one database.
    """
    left, right = make_url(a), make_url(b)
    host_l, host_r = (left.host or "").lower(), (right.host or "").lower()
    if host_l != host_r and not (host_l in _LOOPBACK and host_r in _LOOPBACK):
        return False
    return (left.port or 5432) == (right.port or 5432) and left.database == right.database


def alembic_config(version_locations: list[Path] | None = None) -> Config:
    """Alembic pointed at the test database. `-x db=test` is what env.py reads."""
    cfg = Config(str(ALEMBIC_INI), cmd_opts=Namespace(x=["db=test"]))
    if version_locations is not None:
        # os.pathsep, not a space: alembic.ini sets `path_separator = os`. Joining on a
        # space makes the list one bogus path and the real versions directory is lost,
        # which surfaces as "Can't locate revision". Fixed once before and reintroduced
        # by rewriting this file rather than deleting from it.
        cfg.set_main_option("version_locations", os.pathsep.join(str(p) for p in version_locations))
    return cfg


def _attempt(run: Callable[[], None]) -> str | None:
    # Broad on purpose: a migration that fails is a result to report, not a crash to
    # propagate. An error raised inside a `downgrade()` body would otherwise escape.
    try:
        run()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


@dataclass(frozen=True)
class RoundTrip:
    base: Snapshot
    head: Snapshot
    after_reverse: Snapshot
    after_reapply: Snapshot
    forward_error: str | None = None
    reverse_error: str | None = None
    reapply_error: str | None = None

    @property
    def covered(self) -> int:
        """Objects the migrations create. Zero means the round trip proved nothing."""
        b = {(c, i) for c, i, _ in self.base.objects}
        return len({(c, i) for c, i, _ in self.head.objects} - b)

    @property
    def head_classes(self) -> set[str]:
        """Object classes actually read at head. `covered` counts rows and is satisfied by a
        single query returning enough of them, so the class count needs its own check."""
        return {cls for cls, _, _ in self.head.objects}

    @property
    def differences(self) -> list[str]:
        if self.forward_error is not None:
            return [f"upgrading to head failed: {self.forward_error}"]
        if self.reverse_error is not None:
            return [f"downgrading to base failed: {self.reverse_error}"]
        out = diff(self.base, self.after_reverse)
        if self.reapply_error is not None:
            return [*out, f"upgrading to head again failed: {self.reapply_error}"]
        return [*out, *diff(self.head, self.after_reapply)]

    @property
    def reversible(self) -> bool:
        return not self.differences


def run_round_trip(url: str, cfg: Config) -> RoundTrip:
    """base → head → base → head, snapshotting at each stop.

    Starting with a downgrade makes the result independent of whatever the database held
    when the run began. Re-applying at the end is what catches a `downgrade()` that
    silently drops nothing — the second `CREATE TABLE` is the thing that objects.
    """
    command.downgrade(cfg, "base")
    base = snapshot(url)
    forward_error = _attempt(lambda: command.upgrade(cfg, "head"))
    head = snapshot(url)
    reverse_error = _attempt(lambda: command.downgrade(cfg, "base"))
    after_reverse = snapshot(url)
    reapply_error = _attempt(lambda: command.upgrade(cfg, "head"))
    after_reapply = snapshot(url)
    return RoundTrip(
        base=base,
        head=head,
        after_reverse=after_reverse,
        after_reapply=after_reapply,
        forward_error=forward_error,
        reverse_error=reverse_error,
        reapply_error=reapply_error,
    )
