#!/usr/bin/env python3
"""Prove that the probe-coverage check can fail.

This check has shipped unfailable twice. Fixing it a third time and asserting that the
fix works would be the same move that produced the first two. So the fix carries a
mutation test: break the probe file in each way that matters and require the check to
notice. It runs inside `scripts/verify.sh`, so a future edit that makes the check vacuous
again turns the gate red instead of passing quietly.

Each case copies the real tree into a temp directory, mutates only `preflight.sh`, and
runs the real `check-probes.py` -- not a reimplementation of it. Pure text and python;
no network.
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


def sandbox(tmp: pathlib.Path, preflight: str) -> pathlib.Path:
    """A copy of the tree whose preflight.sh has been replaced with `preflight`."""
    box = pathlib.Path(tempfile.mkdtemp(dir=tmp))
    (box / "docs").mkdir()
    (box / "scripts").mkdir()
    shutil.copy(ROOT / "docs" / "SERVICES.md", box / "docs" / "SERVICES.md")
    shutil.copy(ROOT / "scripts" / "check-probes.py", box / "scripts" / "check-probes.py")
    (box / "scripts" / "preflight.sh").write_text(preflight)
    return box


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

        code, ids_out = run(ROOT, "--ids")
        ids = [i for i in ids_out.splitlines() if i.strip()]
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
        disguises = [
            ('echo "pass {pid} handled elsewhere"', "as a label", "CALL_RE prefix class"),
            ('echo "done; pass {pid} reported ok"', "mid-string", "strip_code quote removal"),
            ("PROBED_ALREADY={pid}", "as a variable value", "CALL_RE outcome-verb anchor"),
            ('cat <<\'NOTES\'\npass {pid} "noted" "x"\nNOTES', "in a heredoc", "heredoc skipping"),
            ('NOTE="probe notes\npass {pid} was handled"', "in a multi-line string", "quote carry"),
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

    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"probe check is failable ({len(ids)} probes mutated, 9 cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
