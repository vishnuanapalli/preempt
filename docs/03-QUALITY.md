<!-- TEMPLATE:UNFILLED — delete this line once this document is genuinely filled in. -->
# Quality bar

Phase 3. Written before implementation starts, so the standard is agreed in advance
rather than negotiated after the fact when it is inconvenient.

## Definition of Done

A story is done when every one of these is true. Not "mostly" — every one.

1. The acceptance criteria in `05-BACKLOG.md` are met, verified by a test.
2. `./scripts/verify.sh` passes, and its output is on record.
3. New behavior has a test that fails without the change.
4. Anything that could not be verified is written down as unverified, with the reason.
5. Any interpretation call made during implementation is logged in `02-DECISIONS.md`.
6. `01-DESIGN.md` is updated if the implementation diverged from it.
7. No attribution trace in code, docs, or commit messages.

## Test strategy

<!-- Fill in the real numbers and tools at Sprint 0. The shape matters more than the
     ratios: many fast tests, fewer slow ones, and end-to-end tests only where the
     integration itself is the thing at risk. -->

| Layer | What it covers | Runs against |
|-------|----------------|--------------|
| Unit | Pure logic, edge cases, error paths | Nothing external |
| Integration | Real database, real HTTP boundaries | A dedicated test database |
| End-to-end | The paths a user actually takes | The running app |

**Test database rule:** integration tests get their own database, never the development
one. A test suite that truncates the database the demo runs on will eventually destroy
demo data at the worst possible moment.

## CI gates

Every push and pull request runs `./scripts/verify.sh` — the same command run locally.
Nothing merges red.

| Gate | What it actually checks | Blocks merge |
|------|-------------------------|--------------|
| Phase | `docs/.phase` names a valid phase | yes |
| Documents | every document due by that phase exists, is over ten lines, and contains none of the template's placeholder strings | yes |
| Attribution | no trace in tracked files, commit messages, or commit author identity, on any branch | yes |
| Secrets | no private key, AWS key id, or token pattern in a tracked file | yes |
| Lint | | yes |
| Type check | | yes |
| Tests | | yes |

The document gate checks that placeholders are gone, not that the prose is good. It
cannot tell a real design document from a plausible one — that is what the review gate
below is for. A skipped stack check is treated as a failure whenever source files are
tracked, so a project cannot go green having never run a test.

## Never-ship list

<!-- The specific failures this project will not repeat. Start with the entries below,
     then add one every time review catches something real — each becomes a
     regression test, not just a note. -->

1. A UI control that looks functional but is not wired to anything.
2. A metric or chart presented as measured when it is synthetic or hardcoded.
3. A model evaluated on the same data it was fit on.
4. Silent truncation — dropped, capped, or skipped records counted as successes.
5. An error swallowed with no log, no metric, and no surfaced signal.
6. A secret in a tracked file, including test fixtures.
7. A "done" claim without the command output that proves it.

## Review gate

Every sprint ends with an adversarial review before it is called done. On a solo project
this review is the substitute for a second engineer, so it is not optional and it does
not get skipped when the sprint ran long. The reviewer reads with fresh context, cites
`file:line`, and reports the command and output behind every claim.

Findings are ranked MUST-FIX / SHOULD-FIX / CONSIDER. A sprint with an open MUST-FIX
is not done. Anything significant that review catches gets a short entry in
`06-LEARNING.md` — what was missed, why it was missed, and the test that now catches it.
