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
stripped before scanning here, so an ordinary label, message, or comment cannot satisfy a
row -- see the limits below for the unusual shell that still can.

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

## This is not a shell parser

It reads `preflight.sh` as logical lines and tracks quotes, comments, heredocs, and
backslash continuations. Every shape below is under test in `scripts/test-probe-gate.py`,
and each one *once counted a probe that does not exist*:

  - an argument that merely follows whitespace, as in `echo hi pass a:b`, where the first
    word of the command is `echo` and `pass` is data;
  - the same with a shell keyword as the argument -- `echo then pass a:b` -- which slipped
    past a first attempt at the rule above that matched keywords anywhere on the line;
  - a heredoc terminator quoted with a backslash, `<<\\EOF`, which is ordinary shell;
  - a line continued from the one above it, whose first word is likewise an argument;
  - an indented terminator for a plain `<<` heredoc, which bash does not honour;
  - a heredoc whose terminator begins with a digit, or holds characters a bare word cannot;
  - a second heredoc opened on the same line as the first;
  - `$'...\\'...'`, where the escaped quote keeps the string open;
  - a quoted span abutting a word, which shell concatenates into one token.

That list is what is *known*, and it grew every time somebody went looking -- four times by
adversarial review after this file claimed to be safe. Treat it as evidence that the list
is incomplete rather than as a bound on how incomplete.

It errs the other way too, and those are named rather than left as mysteries. A probe
written after a construct the command-position chain does not model reads as absent: a
`case` pattern that ends in something other than `)`, a probe inside `$( … )` spanning
lines, or a herestring misread as a heredoc, which hides everything after it. If a real
probe is reported missing and you can see the call, that is the place to look.

On anything ambiguous the scanner errs toward reporting a probe *absent*: a false FAIL is
loud and gets fixed, where a false PASS is the failure this file exists to prevent. That is
the design intent and not a guarantee -- every shape above was a counterexample to it being
stated as one.

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
#
# A command starts at the beginning of a logical line or after a separator. Merely being
# preceded by whitespace is NOT enough: an early version accepted that, so `echo hi pass a:b`
# counted a probe where `pass` is an argument to echo.
#
# Words that may precede a command without being it -- `if`, `!`, `{`, a `VAR=x` assignment
# -- are allowed in between, but each must itself sit at command position. Offering them as
# a bare alternative instead was the same bug wearing a hat: `\b(?:then|do)\b` matched the
# word anywhere, so `echo then pass a:b` counted again.
#
# The separator class holds operators only. `{` and `}` are reserved *words*, so they belong
# in the chain rather than the class: with `{` unconditional, `echo {pass a:b } done` counted
# a probe inside a brace-expansion argument. `{` stays in LEAD because `{ pass a:b; }` is a
# real command group and dropping it outright would lose that.
LEAD = r"(?:then|else|elif|do|if|while|until|time|!|\{|[A-Za-z_][A-Za-z0-9_]*=\S*)"
CALL_RE = re.compile(rf"(?:^|[;&|()])\s*(?:{LEAD}\s+)*(?:pass|fail|waive)\s+({ID})(?=\s|$)")

# The start of a heredoc, whose body is data rather than code. Matched at the cursor, so it
# only fires outside quotes. Group 1 is the `-` form, which alone permits a tab-indented
# terminator. A quoted terminator may hold anything -- `<<'EOF.txt'` is legal -- while an
# unquoted one is a bare word, and it may begin with a digit: `<<'9NOTES'` is a real heredoc
# that an earlier letters-only pattern did not track, leaving its body scanned as code.
# `<<\EOF` is the ordinary way to write a non-expanding heredoc without quoting, so the
# optional backslash is not an edge case; without it that body was scanned as code.
HEREDOC_RE = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z0-9_]+))")

# Stands in for a removed quoted span. Deliberately not a space: shell concatenates a
# quoted span with the word beside it, so `echo "already"pass x:y` is one word `alreadypass`
# and not a command named `pass`. Substituting a space manufactured that command and counted
# a probe that does not exist. Substituting nothing would merge tokens the other way, so a
# character that can be neither whitespace nor part of an id is the only faithful stand-in.
QUOTED = "\x00"

# A row carrying either marker is exempt from needing a probe. The marker has to be
# written into the manifest deliberately, next to the reason it is there.
EXEMPT = ("NOT PROVISIONED", "NO DIRECT PROBE")


def strip_code(
    line: str, quote: str | None = None
) -> tuple[str, str | None, list[tuple[str, bool]]]:
    """Split a shell line into executable text, trailing quote state, and heredoc openers.

    One left-to-right walk does all three, because all three need to know whether the
    cursor is inside a quote. Quoted spans and comments are removed. `quote` carries an
    unterminated string in from the previous line, so the continuation lines of a
    multi-line assignment are treated as the data they are rather than as code. It is
    `"`, `'`, or `$'` -- the last because ANSI-C quoting honours `\\'` as a literal quote,
    where plain `'...'` has no escapes at all and ends at the first `'`.

    Heredocs are detected here rather than by scanning the stripped result: the terminator
    is usually quoted (`cat <<'NOTES'`), so by the time quotes are gone there is nothing
    left to match. All openers on the line are returned, in order, because `cat <<'A' <<'B'`
    queues two bodies and tracking only the first scans the second as code.

    On ambiguity this errs toward reporting a probe absent rather than present, because a
    false FAIL is loud and a false PASS is the failure this file exists to prevent. It is
    not a shell parser and does not claim to be: see the module docstring for the shapes
    that are known to fool it, and `scripts/test-probe-gate.py` for the ones under test.
    """
    out: list[str] = []
    openers: list[tuple[str, bool]] = []
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if quote is not None:
            # Backslash escapes exist inside "..." and $'...', but never inside '...'.
            if c == "\\" and quote in ('"', "$'") and i + 1 < n:
                i += 2
                continue
            if c == quote[-1]:
                quote = None
            i += 1
            continue
        if line.startswith("$'", i):
            quote = "$'"
            out.append(QUOTED)
            i += 2
            continue
        if c in "\"'":
            quote = c
            out.append(QUOTED)
            i += 1
            continue
        if c == "#" and (not out or out[-1].isspace()):
            break
        # `<<<` is a herestring, not a heredoc: it consumes a word, not the lines below.
        # All three characters go at once — stepping over one at a time leaves `<<"word"`,
        # which reads as a heredoc and swallows the rest of the file.
        if line.startswith("<<<", i):
            out.append("<<<")
            i += 3
            continue
        if line.startswith("<<", i):
            opened = HEREDOC_RE.match(line, i)
            if opened:
                quoted_sq, quoted_dq, bare = opened.group(2, 3, 4)
                word = quoted_sq if quoted_sq is not None else quoted_dq
                openers.append((word if word is not None else bare, opened.group(1) == "-"))
                out.append(QUOTED)
                i = opened.end()
                continue
        out.append(c)
        i += 1
    return "".join(out), quote, openers


def executable_lines(source: str) -> list[str]:
    """The executable text of each line: heredoc bodies dropped, quote state carried.

    A heredoc body is data. Scanning it as code lets `cat <<'NOTES' ... NOTES` hold text
    that reads as a probe call -- a false PASS.

    The terminator must match the line exactly, and only the `<<-` form tolerates leading
    tabs. Accepting an indented terminator for plain `<<` ends the body early and scans the
    rest of it as code, which is the same false PASS by a subtler route.
    """
    lines: list[str] = []
    quote: str | None = None
    pending: list[tuple[str, bool]] = []
    continued = False
    for raw in source.splitlines():
        if pending:
            terminator, dash = pending[0]
            if (raw.lstrip("\t") if dash else raw) == terminator:
                pending.pop(0)
            continue
        code, quote, openers = strip_code(raw, quote)
        pending.extend(openers)

        # A line ending in an unescaped backslash continues the one below it, so the next
        # line's first word is an argument rather than a command. Joining them is what lets
        # CALL_RE's command-position rule see that; scanning them apart made every
        # continuation line look like a fresh command start.
        trimmed = code.rstrip()
        continues = trimmed.endswith("\\") and not trimmed.endswith("\\\\")
        if continues:
            code = trimmed[:-1]
        if continued and lines:
            lines[-1] += code
        else:
            lines.append(code)
        continued = continues
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
        # This exists for the message, not the verdict, and no test can isolate it: `want`
        # is derived from `rows`, so an empty table forces an empty `want`, which the
        # vacuity guard below already fails on. It is strictly subsumed -- there is no
        # manifest where this fires and that one would not. Said out loud because a reviewer
        # reported its removal as a missed sabotage, and the honest answer is that removing
        # it changes which sentence prints and nothing else.
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
