#!/usr/bin/env python3
"""Bind every service in the manifest to a probe that actually exists.

`docs/SERVICES.md` promises that every external dependency this project leans on has a
probe in `scripts/preflight.sh`. This is the check that makes the promise falsifiable.

The binding is a **probe id in argument position**, unquoted, on the outcome call:

    pass vercel:auth "vercel cli authenticated" "$who"
         ^^^^^^^^^^^ declared in the Probe column of docs/SERVICES.md

Two earlier versions of this check searched the probe file's *label text* for the service
name, and both shipped unfailable. The Vercel row was satisfied by the label
"npx (runs vercel cli)"; the Docker row by a postgres failure message. Deleting all four
Vercel probes still reported that every service had one. Quoted spans and comments are
stripped before scanning here, so no label, message, or comment can satisfy a row.

Modes:
  --static        Every declared id appears as an outcome call in preflight.sh, and every
                  outcome call in preflight.sh is declared. Offline and deterministic;
                  this is what the gate runs.
  --emitted FILE  Every declared id appears in FILE, the ids preflight.sh actually printed
                  during a run. Catches a probe that exists in the source but never
                  executes because its branch was not taken -- which --static cannot see.
                  preflight.sh runs this against itself before printing its verdict.
  --ids           Print the declared ids, one per line. For the mutation test.

## What --static does not prove, stated rather than left to be discovered

`--static` proves an outcome call for the id *exists in the file*. It does not prove the
call is ever *reached*. Move every probe for a service into a function nobody invokes, an
`if false` branch, a block below `exit 0`, or after a `:` builtin, and `--static` is green
while the service is genuinely unprobed. Heredoc bodies and multi-line strings used to
fool it the same way; those two are now parsed as the data they are, but the class is not
closed and cannot be by static analysis.

`--emitted` is what actually proves reachability, and `preflight.sh` runs it against
itself. **Nothing automated runs `preflight.sh`** — not CI, not the gate — so in practice
reachability is proven only when someone runs preflight by hand. The gate deliberately
does not run it: the probes are network calls, and a slow flaky gate gets switched off.

Two things even `--emitted` cannot see:
  - a probe whose body was gutted while its outcome call was left behind;
  - the same, with the call changed to `waive`, which reports, satisfies coverage, and
    does not fail preflight. That is a one-line edit, not an exotic one.

`scripts/test-probe-gate.py` proves that the failure modes which *are* reachable do fail.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "SERVICES.md"
PREFLIGHT = ROOT / "scripts" / "preflight.sh"

# A probe id: two lowercase slugs joined by a colon. Deliberately narrow, so that nothing
# else written in either file can be mistaken for one.
ID = r"[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*"
ID_RE = re.compile(rf"^{ID}$")

# An outcome call: pass/fail/waive at the start of a command, id as the first argument.
# Applied only to source with quoted spans already removed, so an id appearing inside a
# label is invisible here -- which is the whole point.
CALL_RE = re.compile(rf"(?:^|[\s;&|()])(?:pass|fail|waive)\s+({ID})(?=\s|$)")

# The start of a heredoc, whose body is data rather than code. Matched at the cursor, so
# it only fires outside quotes. The quote around the terminator is optional in shell and
# irrelevant here; only the word matters.
HEREDOC_RE = re.compile(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")

# A row carrying either marker is exempt from needing a probe. The marker has to be
# written into the manifest deliberately, next to the reason it is there.
EXEMPT = ("NOT PROVISIONED", "NO DIRECT PROBE")


def strip_code(line: str, quote: str | None = None) -> tuple[str, str | None, str | None]:
    """Split a shell line into executable text, trailing quote state, and heredoc opener.

    One left-to-right walk does all three, because all three need to know whether the
    cursor is inside a quote. Quoted spans and comments are removed. `quote` carries an
    unterminated string in from the previous line, so the continuation lines of a
    multi-line assignment are treated as the data they are rather than as code.

    Heredocs are detected here rather than by scanning the stripped result: the terminator
    is usually quoted (`cat <<'NOTES'`), so by the time quotes are gone there is nothing
    left to match. That was a real bug, caught by this file's own heredoc mutation case.

    Ambiguous input fails toward a false FAIL -- a call missed and reported as absent --
    never toward a false PASS. A `#` inside a double-quoted string ends the line early; an
    unbalanced quote hides the lines after it; `a << b` as an arithmetic shift would be
    read as a heredoc. All are loud, and none invents a probe that does not exist.
    """
    out: list[str] = []
    terminator: str | None = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote is not None:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            out.append(" ")  # a stripped span still separates two words
            i += 1
            continue
        if c == "#" and (not out or out[-1].isspace()):
            break
        if terminator is None and line.startswith("<<", i):
            opened = HEREDOC_RE.match(line, i)
            if opened:
                terminator = opened.group(1)
                out.append(" ")
                i = opened.end()
                continue
        out.append(c)
        i += 1
    return "".join(out), quote, terminator


def executable_lines(source: str) -> list[str]:
    """The executable text of each line: heredoc bodies dropped, quote state carried.

    A heredoc body is data. Scanning it as code lets `cat <<'NOTES' ... NOTES` hold text
    that reads as a probe call, which is a false PASS -- the one direction this must never
    fail in.
    """
    lines: list[str] = []
    quote: str | None = None
    terminator: str | None = None
    for raw in source.splitlines():
        if terminator is not None:
            if raw.strip() == terminator:
                terminator = None
            continue
        code, quote, opened = strip_code(raw, quote)
        if opened is not None:
            terminator = opened
        lines.append(code)
    return lines


def read_manifest() -> tuple[list[tuple[str, bool, list[str]]], list[str]]:
    """Parse SERVICES.md into (name, exempt, declared_ids) rows, plus any parse errors."""
    errors: list[str] = []
    if not MANIFEST.exists():
        return [], [f"{MANIFEST.name} is missing"]

    header: list[str] | None = None
    rows: list[tuple[str, bool, list[str]]] = []
    probe_col = -1

    for raw in MANIFEST.read_text().splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            continue  # the |---|---| separator
        if header is None:
            header = [re.sub(r"[*`]", "", c).strip().lower() for c in cells]
            if "probe" not in header:
                errors.append(
                    "the services table has no 'Probe' column -- nothing declares which "
                    "probes must exist"
                )
                return [], errors
            probe_col = header.index("probe")
            continue

        name = re.sub(r"[*`]", "", cells[0]).strip()
        joined = " ".join(cells).upper()
        exempt = any(marker in joined for marker in EXEMPT)
        cell = cells[probe_col] if 0 <= probe_col < len(cells) else ""
        # An exempt row declares nothing — that is what the exemption means. Without this
        # it cannot explain itself by naming another row's probe, and the Neon row does
        # exactly that. Marking a row exempt does not hide its probes: any call left in
        # preflight.sh then reports as undeclared, which is loud rather than silent.
        ids = [] if exempt else [t for t in re.findall(r"`([^`]+)`", cell) if ID_RE.match(t)]
        rows.append((name, exempt, ids))

    if header is None:
        errors.append("the services table is missing entirely")
    return rows, errors


def found_ids() -> set[str]:
    """Every probe id appearing in argument position on an outcome call."""
    if not PREFLIGHT.exists():
        return set()
    return {
        m.group(1)
        for line in executable_lines(PREFLIGHT.read_text())
        for m in CALL_RE.finditer(line)
    }


def declared(rows: list[tuple[str, bool, list[str]]]) -> set[str]:
    return {i for _, _, ids in rows for i in ids}


def check_rows(rows: list[tuple[str, bool, list[str]]]) -> list[str]:
    """Row-level problems: an empty table, or a live row that declares no probe at all."""
    if not rows:
        return ["docs/SERVICES.md lists no services -- the table was never filled in"]
    problems = []
    for name, exempt, ids in rows:
        if not exempt and not ids:
            problems.append(
                f"'{name}' declares no probe id in its Probe column -- write one, or mark "
                f"the row {' / '.join(EXEMPT)} with the reason"
            )
    return problems


def main() -> int:
    argv = sys.argv[1:]
    mode = argv[0] if argv else "--static"

    rows, errors = read_manifest()
    if errors:
        print("\n".join(errors))
        return 1

    if mode == "--ids":
        for i in sorted(declared(rows)):
            print(i)
        return 0

    problems = check_rows(rows)
    want = declared(rows)
    if not want and not problems:
        problems.append("no probe ids are declared anywhere -- the check would be vacuous")

    if mode == "--static":
        have = found_ids()
        for name, _, ids in rows:
            for i in sorted(set(ids) - have):
                problems.append(
                    f"'{name}' declares probe '{i}' but no pass/fail/waive call in "
                    f"preflight.sh carries it"
                )
        for i in sorted(have - want):
            problems.append(f"preflight.sh emits probe '{i}', which no row of SERVICES.md declares")
        # Says what it proves and no more. "Every service has a probe" overstated it:
        # --static shows the call exists, not that anything ever reaches it.
        summary = (
            f"every probe SERVICES.md declares exists in preflight.sh "
            f"({sum(1 for _, e, _ in rows if not e)} services, {len(want)} probes, "
            f"{sum(1 for _, e, _ in rows if e)} exempt) — existence, not reachability"
        )

    elif mode == "--emitted":
        if len(argv) < 2:
            print("--emitted needs the path of the file listing emitted ids")
            return 1
        path = pathlib.Path(argv[1])
        emitted = (
            {ln.strip() for ln in path.read_text().splitlines() if ln.strip()}
            if path.exists()
            else set()
        )
        for name, _, ids in rows:
            for i in sorted(set(ids) - emitted):
                problems.append(f"'{name}' declares probe '{i}' but it never ran")
        for i in sorted(emitted - want):
            problems.append(f"probe '{i}' ran but no row of SERVICES.md declares it")
        summary = f"all {len(want)} declared probes ran"

    else:
        print(f"unknown mode '{mode}' -- expected --static, --emitted FILE, or --ids")
        return 1

    if problems:
        print("\n".join(problems))
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
