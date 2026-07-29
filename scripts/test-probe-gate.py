#!/usr/bin/env python3
"""Prove that the probe-coverage check can fail.

This check has shipped unfailable twice. Fixing it a third time and asserting that the
fix works would be the same move that produced the first two. So the fix carries a
mutation test: break the probe file in each way that matters and require the check to
notice. It runs inside `scripts/verify.sh`, so a future edit that makes the check vacuous
again turns the gate red instead of passing quietly.

Each case copies the real tree into a temp directory, mutates one of the check's **two**
inputs -- `preflight.sh` or `docs/SERVICES.md` -- and runs the real `check-probes.py`, not
a reimplementation of it. Pure text and python; no network.

Mutating only `preflight.sh` is not enough, and was the second thing this suite got wrong:
the guards that stop the check being *vacuous* all live on the manifest side, so they sat
unexercised while the suite reported itself complete.

A case earns its place by being defeated by one identifiable part of the check. Two of the
guards genuinely overlap -- delete either the empty-table guard or the vacuity guard and an
empty manifest still fails; delete both and it passes, which is the case that covers them.

Cases come in both directions, which was the third thing this suite got wrong. For four
rounds every case asserted the check goes *red*, so nothing could catch a regression that
made it miss a real probe -- and one duly slipped through: removing the command-prefix chain
reverted four fixes at once with the suite still green. The `keeps` block asserts the
opposite, on shapes bash genuinely runs.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECK = "scripts/check-probes.py"


def run(cwd: pathlib.Path, *args: str) -> tuple[int, str]:
    # The real check, invoked the way the gate invokes it, rather than imported — a test
    # that reimplements or monkeypatches the thing under test is how the last two versions
    # of this check were "verified". Every element of the command is a literal or this
    # interpreter's own path, so there is no untrusted input to sanitise (S603).
    p = subprocess.run(  # noqa: S603
        [sys.executable, CHECK, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return p.returncode, (p.stdout + p.stderr).strip()


def sandbox(tmp: pathlib.Path, preflight: str, manifest: str | None = None) -> pathlib.Path:
    """A copy of the tree with preflight.sh -- and optionally SERVICES.md -- replaced.

    The check has two inputs. An earlier version of this suite mutated only preflight.sh,
    which left every guard on the manifest side unexercised: the empty-table, all-exempt,
    and blank-Probe-cell guards could all be deleted with this suite still green.
    """
    box = pathlib.Path(tempfile.mkdtemp(dir=tmp))
    (box / "docs").mkdir()
    (box / "scripts").mkdir()
    if manifest is None:
        shutil.copy(ROOT / "docs" / "SERVICES.md", box / "docs" / "SERVICES.md")
    else:
        (box / "docs" / "SERVICES.md").write_text(manifest)
    shutil.copy(ROOT / "scripts" / "check-probes.py", box / "scripts" / "check-probes.py")
    (box / "scripts" / "preflight.sh").write_text(preflight)
    return box


def edit_manifest(
    text: str,
    *,
    drop_rows: bool = False,
    all_exempt: bool = False,
    blank: str | None = None,
    move_ids: str | None = None,
) -> str:
    """Rewrite the services table.

    `move_ids` shifts a row's probe ids out of the Probe cell into a neighbouring one,
    which is the original label-text defect wearing the manifest's clothes: prose standing
    in for a declaration. It pins that the *column* is what is read, not the row.
    """
    lines = text.splitlines()
    header_at, data_at, probe_col = None, [], -1
    for n, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            continue
        if header_at is None:
            header_at = n
            probe_col = [re.sub(r"[*`]", "", c).strip().lower() for c in cells].index("probe")
        else:
            data_at.append(n)

    out = []
    for n, line in enumerate(lines):
        if n not in data_at:
            out.append(line)
            continue
        if drop_rows:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        name = re.sub(r"[*`]", "", cells[0]).strip().lower()
        if all_exempt:
            cells[probe_col] = "NOT PROVISIONED"
        elif blank and blank.lower() in name:
            cells[probe_col] = ""
        elif move_ids and move_ids.lower() in name:
            spare = 1 if probe_col != 1 else 2
            cells[spare] = f"{cells[spare]} -- probes: {cells[probe_col]}"
            cells[probe_col] = ""
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main() -> int:
    source = (ROOT / "scripts" / "preflight.sh").read_text()
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)

        # Control. If the untouched tree does not pass, every mutation below "fails" for
        # the wrong reason and the whole suite means nothing.
        code, out = run(sandbox(tmp, source), "--static")
        if code != 0:
            print(f"  control: the untouched tree does not pass -- {out}")
            print("  every case below would be meaningless; fix this first")
            return 1

        # Only well-formed ids, because run() folds stderr into its output and anything the
        # interpreter prints there would otherwise become a fake id: a SyntaxWarning from a
        # docstring once did exactly that, and the suite reported four failures about
        # "deleting probe '<warning text>'". Garbage in the input must not become findings.
        code, ids_out = run(ROOT, "--ids")
        well_formed = re.compile(r"^[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*$")
        ids = [i.strip() for i in ids_out.splitlines() if well_formed.match(i.strip())]
        if code != 0 or not ids:
            print("  docs/SERVICES.md declares no probe ids, so there is nothing to mutate")
            print("  -- write them into the Probe column before this can mean anything")
            return 1

        # 1. Deleting any single probe must be detected. This is the property the two
        #    previous versions lacked: all four Vercel probes could be deleted and the
        #    check still reported PASS.
        for pid in ids:
            call = re.compile(rf"(?:^|[\s;&|()])(?:pass|fail|waive)\s+{re.escape(pid)}(?=\s|$)")
            mutated = "\n".join(ln for ln in source.splitlines() if not call.search(ln))
            if mutated == source:
                failures.append(f"probe '{pid}' is declared but has no outcome call to delete")
                continue
            code, out = run(sandbox(tmp, mutated), "--static")
            if code == 0:
                failures.append(f"deleting probe '{pid}' from preflight.sh does not fail the check")

        # 2. Deleting a whole service's probes must be detected. The recorded defect was
        #    reported at this granularity, so it is tested at this granularity too.
        for service in sorted({i.split(":")[0] for i in ids}):
            call = re.compile(
                rf"(?:^|[\s;&|()])(?:pass|fail|waive)\s+{re.escape(service)}:[a-z0-9-]+(?=\s|$)"
            )
            mutated = "\n".join(ln for ln in source.splitlines() if not call.search(ln))
            code, out = run(sandbox(tmp, mutated), "--static")
            if code == 0:
                failures.append(f"deleting every '{service}' probe does not fail the check")

        # 3. The id present in the file but not as a probe -- the defect that shipped
        #    twice. One disguise is not enough: each shape below is defeated by a
        #    *different* part of check-probes.py, so one case per part. Sabotage that part
        #    and its case must go green; that is what makes these tests of the mechanism
        #    rather than of some incidental rule.
        #
        #    An earlier version of this suite had only the first shape, and it was worthless
        #    for the stripping: the id sits immediately after the opening quote, so it is
        #    rejected by CALL_RE's command-position prefix class before quote removal is
        #    ever consulted. It went red with the stripping deleted. Hence the mid-string
        #    shape, where the id is preceded by whitespace *inside* the quotes.
        #
        #    The last four were live false PASSes, each found by an adversarial review
        #    rather than by this suite. Every one counted a probe that does not exist, so
        #    each is now pinned here: bash was run against all four to confirm none of them
        #    actually executes a probe.
        disguises = [
            ('echo "pass {pid} handled elsewhere"', "as a label", "CALL_RE prefix class"),
            ('echo "done; pass {pid} reported ok"', "mid-string", "strip_code quote removal"),
            ("PROBED_ALREADY={pid}", "as a variable value", "CALL_RE outcome-verb anchor"),
            ('cat <<\'NOTES\'\npass {pid} "noted" "x"\nNOTES', "in a heredoc", "heredoc skipping"),
            ('NOTE="probe notes\npass {pid} was handled"', "in a multi-line string", "quote carry"),
            # bash ends a plain `<<` body only on an unindented terminator.
            (
                'cat <<\'NOTES\'\n  NOTES\npass {pid} "x" "y"\nNOTES',
                "under an indented heredoc terminator",
                "exact terminator matching",
            ),
            # bash queues both bodies; tracking only the first scans the second as code.
            (
                "cat <<'A' <<'B'\nA\npass {pid} \"x\" \"y\"\nB",
                "in the second of two heredocs",
                "the heredoc queue",
            ),
            # In $'...', \' is a literal quote and the string stays open.
            (
                'msg=$\'oops\\\'\npass {pid} "x" "y"\n\'',
                "inside ANSI-C quoting",
                "$'...' escape handling",
            ),
            # Shell concatenates a quoted span with the word beside it: one token, no command.
            ('echo "already"pass {pid} done', "abutting a quoted span", "command-position rule"),
            # The same concatenation on the other side: bash reads one argument `<pid>x`, so
            # no probe with this id runs. Only the sentinel sees that -- substituting a space
            # for the quoted span would leave the id looking correctly terminated.
            (
                'pass {pid}"x" "y"',
                "with its id running into a quoted span",
                "the QUOTED sentinel",
            ),
            # `pass` here is an argument to echo -- preceded by whitespace, but not a command.
            (
                "echo noted pass {pid} done",
                "as an argument mid-command",
                "CALL_RE's command-position rule",
            ),
            # A trailing backslash makes the next line arguments of the same command.
            (
                'echo "noted" \\\npass {pid} "x" "y"',
                "on a continued line",
                "continuation joining",
            ),
            # A bare heredoc terminator may begin with a digit.
            (
                'cat <<\'9NOTES\'\npass {pid} "x" "y"\n9NOTES',
                "in a digit-terminated heredoc",
                "the heredoc terminator pattern",
            ),
            # A quoted terminator may hold what a bare word cannot.
            (
                'cat <<\'EOF.txt\'\npass {pid} "x" "y"\nEOF.txt',
                "in a dotted-terminator heredoc",
                "quoted heredoc terminators",
            ),
            # A shell keyword as an argument. A first attempt at the command-position rule
            # offered keywords as a bare alternative, which matched the word anywhere on the
            # line and reopened the argument hole that same rule was written to close.
            (
                "echo then pass {pid} done",
                "after a keyword in argument position",
                "requiring the keyword to be at command position too",
            ),
            (
                "echo do pass {pid} done",
                "after a loop keyword in argument position",
                "requiring the keyword to be at command position too",
            ),
            # `{` is a reserved word, not an operator: it introduces a command only when it
            # is itself at command position. Unconditional in the separator class, a probe id
            # inside a brace-expansion argument counted.
            # Braces are doubled because these templates go through str.format.
            (
                "echo {{pass {pid} }} done",
                "inside a brace-expansion argument",
                "`{` earning command position",
            ),
            # `<<\EOF` is the ordinary way to write a non-expanding heredoc without quotes.
            (
                'cat <<\\EOF\npass {pid} "x" "y"\nEOF',
                "in a backslash-quoted heredoc",
                "backslash heredoc terminators",
            ),
        ]
        pid = ids[0]
        call = re.compile(rf"(?:^|[\s;&|()])(?:pass|fail|waive)\s+{re.escape(pid)}(?=\s|$)")
        for template, shape, guarded_by in disguises:
            replacement = template.format(pid=pid)
            mutated = "\n".join(
                replacement if call.search(ln) else ln for ln in source.splitlines()
            )
            if mutated == source:
                failures.append(f"could not build the '{shape}' case for '{pid}'")
                continue
            code, out = run(sandbox(tmp, mutated), "--static")
            if code == 0:
                failures.append(
                    f"probe '{pid}' present only {shape} satisfies the check "
                    f"-- {guarded_by} is not doing its job"
                )

        # 4. A commented-out probe is a deleted probe.
        pid = ids[0]
        commented = re.sub(
            rf"(?m)^(\s*)(.*(?:pass|fail|waive)\s+{re.escape(pid)}\s)",
            r"\1# \2",
            source,
        )
        if commented == source:
            failures.append(f"could not build the commented-out case for '{pid}'")
        else:
            code, out = run(sandbox(tmp, commented), "--static")
            if code == 0:
                failures.append(f"commenting out probe '{pid}' does not fail the check")

        # 5. An undeclared probe must be reported too, so a typo in an id reads as a typo
        #    rather than silently covering nothing.
        code, out = run(sandbox(tmp, source + '\npass ghost:probe "unlisted" "x"\n'), "--static")
        if code == 0:
            failures.append("a probe no row of SERVICES.md declares does not fail the check")

        # 6. The manifest is the check's other input, and the guards that stop the check
        #    being *vacuous* all live on that side. Mutating only preflight.sh left all
        #    three untested -- and an empty table beside a preflight with no probes is
        #    precisely the state a fresh project from the template starts in, so these are
        #    the guards between that state and a green section 4 at phase 2.
        manifest = (ROOT / "docs" / "SERVICES.md").read_text()
        stub = "#!/usr/bin/env bash\nexit 0\n"
        service = ids[0].split(":")[0]
        service_calls = re.compile(
            rf"(?:^|[\s;&|()])(?:pass|fail|waive)\s+{re.escape(service)}:[a-z0-9-]+(?=\s|$)"
        )
        manifest_cases = [
            (
                edit_manifest(manifest, drop_rows=True),
                stub,
                "an empty services table",
                "the empty-table guard",
            ),
            (
                edit_manifest(manifest, all_exempt=True),
                stub,
                "every row marked exempt",
                "the vacuity guard",
            ),
            # The row's probes go too, so the row-level guard is the only thing left to
            # catch it -- otherwise the undeclared-probe rule would, and this would test
            # that instead.
            (
                edit_manifest(manifest, blank=service),
                "\n".join(ln for ln in source.splitlines() if not service_calls.search(ln)),
                f"'{service}' left with a blank Probe cell",
                "the row-level guard",
            ),
            # The ids move out of the Probe cell into a neighbouring column as prose.
            # Reading the whole row would satisfy the declaration from that prose, which is
            # the original label-text defect wearing the manifest's clothes.
            (
                edit_manifest(manifest, move_ids=service),
                source,
                f"'{service}' declaring its ids outside the Probe column",
                "reading the Probe column rather than the whole row",
            ),
        ]
        for mutated_manifest, preflight, shape, guarded_by in manifest_cases:
            code, out = run(sandbox(tmp, preflight, manifest=mutated_manifest), "--static")
            if code == 0:
                failures.append(
                    f"{shape} does not fail the check -- {guarded_by} is not doing its job"
                )

        # 7. A declared id must match the call exactly. Without CALL_RE's trailing boundary
        #    a longer id in preflight.sh silently satisfies a shorter declared one, so a
        #    rename drifts away from the manifest without the gate noticing.
        #
        #    The suffix must start with a character outside the id charset. `-v2` does not
        #    isolate anything: `-` is a legal id character, so the greedy match simply takes
        #    the longer id and the case goes red whether the boundary is there or not. `_`
        #    stops the match, which is what makes this a test of the boundary.
        pid = ids[0]
        renamed = re.sub(
            rf"((?:^|[\s;&|()])(?:pass|fail|waive)\s+{re.escape(pid)})(?=\s|$)", r"\1_v2", source
        )
        if renamed == source:
            failures.append(f"could not build the rename case for '{pid}'")
        else:
            code, out = run(sandbox(tmp, renamed), "--static")
            if code == 0:
                failures.append(
                    f"renaming '{pid}' to '{pid}_v2' in preflight.sh does not fail the check "
                    f"-- CALL_RE's trailing boundary is not doing its job"
                )

        # 8. Cases that must stay GREEN.
        #
        #    Every case above asserts the check goes red, which means a regression that makes
        #    it *miss* a real probe has never been catchable at all. That is not a gap in the
        #    cases, it is a gap in the shape of the suite: deleting the whole command-prefix
        #    chain reverted four fixes at once and left this green, and the herestring branch
        #    had been unpinned for three rounds for the same reason.
        #
        #    Each shape below is one bash genuinely runs, so the check must still find the id.
        keeps = [
            ('A=1 pass {pid} "x" "y"', "environment-prefixed", "the LEAD chain"),
            ('if pass {pid} "x" "y"; then :; fi', "an if condition", "the LEAD chain"),
            ('time pass {pid} "x" "y"', "time-prefixed", "the LEAD chain"),
            ('if ! pass {pid} "x" "y"; then :; fi', "negated", "the LEAD chain"),
            ('{ pass {pid} "x" "y"; }', "inside a brace group", "`{` in the LEAD chain"),
            ('grep -q x <<<"m"\npass {pid} "x" "y"', "after a herestring", "the herestring branch"),
            (
                '[ -n "$t" ] && pass {pid} "$t" \\\n    || fail {pid} "no"',
                "in an && / || chain",
                "continuation joining",
            ),
        ]
        pid = ids[0]
        call = re.compile(rf"(?:^|[\s;&|()])(?:pass|fail|waive)\s+{re.escape(pid)}(?=\s|$)")
        for template, shape, mechanism in keeps:
            replacement = template.replace("{pid}", pid)
            mutated = "\n".join(
                replacement if call.search(ln) else ln for ln in source.splitlines()
            )
            code, out = run(sandbox(tmp, mutated), "--static")
            if code != 0:
                failures.append(
                    f"a probe written {shape} is reported missing when bash would run it "
                    f"-- {mechanism} regressed: {out.splitlines()[0] if out else ''}"
                )

    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    cases = 5 + len(disguises) + len(manifest_cases) + len(keeps)
    print(f"probe check is failable ({len(ids)} probes mutated, {cases} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
