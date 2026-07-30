#!/usr/bin/env python3
"""Is the verification proportionate to the code it verifies?

Ledger rule R9. This exists because prose did not stop it: this project accumulated 1,581
lines of tests against 300 lines of application, to verify a migration whose `upgrade()` and
`downgrade()` are both `pass`. Every individual finding that produced was real, which is why
a per-finding judgement never says "enough" — only a total can.

Deliberately crude. Line counts are a bad proxy for value and a fine proxy for volume, and
volume was the problem. It is offline and deterministic, which is what section 4 of the gate
requires of itself.

Resolution when this fails is one of two things, and raising the ceiling is neither:
  - delete verification that covers code which does not exist yet, or
  - defer the criterion that demanded it to the story that builds the code (D-016 rule 1).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Generous on purpose. A healthy mature project sits near 1:1 or 2:1; this is set to catch
#: 5:1, not to police 2.1:1.
#:
#: It was 2.0 for one commit, which was a mistake worth recording: the post-trim ratio was
#: 1.9967, so the ceiling sat *at* the achieved value and left one line of headroom. That
#: turns a proportionality budget into a ratchet — the next necessary fix breaches it, and
#: the note below forbids raising it, so the only legal move is deleting something
#: load-bearing. Found by review; see D-018.
#:
#: The distinction that keeps this honest: setting a ceiling correctly is not the same as
#: raising one to avoid deleting bloat. The first is allowed once, with a reason on record.
#: The second is what R12 forbids. If you are here because the number is inconvenient,
#: you are doing the second one.
CEILING = 2.5


def count(paths: list[Path]) -> tuple[int, dict[str, int]]:
    total = 0
    per_file: dict[str, int] = {}
    for path in sorted(paths):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        lines = len(path.read_text().splitlines())
        per_file[str(path.relative_to(ROOT))] = lines
        total += lines
    return total, per_file


def main() -> int:
    app, _ = count(list((ROOT / "api" / "app").rglob("*.py")))
    tests, per_test = count(list((ROOT / "api" / "tests").rglob("*.py")))

    if app == 0:
        print("no application code yet, so nothing to be proportionate to")
        return 0

    ratio = tests / app
    verdict = "PASS" if ratio <= CEILING else "FAIL"
    print(
        # Two decimals, not one: `:.1f` printed 1.9967 as "2.0:1" and hid that the margin
        # was a single line.
        f"{verdict}  verification {tests} lines / application {app} lines "
        f"= {ratio:.2f}:1 (ceiling {CEILING}:1, headroom {int(app * CEILING) - tests} lines)"
    )

    if verdict == "FAIL":
        print("\n  largest verification files:")
        for name, lines in sorted(per_test.items(), key=lambda kv: -kv[1])[:4]:
            print(f"    {lines:>5}  {name}")
        print(
            f"\n  Over the ceiling by {tests - int(app * CEILING)} lines. Delete verification"
            "\n  covering code that does not exist yet, or defer the criterion that demanded"
            "\n  it to the story that builds the code (D-016 rule 1). Raising CEILING is not"
            "\n  a resolution — R12: the enforcement is the point, not the number."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
