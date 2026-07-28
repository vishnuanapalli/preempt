# Preempt — quality bar

Phase 3. Written before implementation, so the standard is agreed in advance rather than
negotiated afterwards when it is inconvenient.

## Definition of Done

A story is done when every one of these is true. Not most.

1. The acceptance criteria in `05-BACKLOG.md` are met, proven by a test.
2. `./scripts/verify.sh` passes, and its output is on record.
3. New behaviour has a test that **fails without the change**. A test that passes against
   the unfixed code proves nothing.
4. Anything that could not be verified is written down as unverified, with the reason.
5. Any interpretation call made during implementation is logged in `02-DECISIONS.md`.
6. `01-DESIGN.md` is updated if the implementation diverged from it.
7. No docstring, comment, or document claims a property the code does not have.

Item 7 is not boilerplate. It is the failure mode that produced most of the defects below.

## Test strategy

| Layer | Covers | Runs against |
|-------|--------|--------------|
| Unit | Pure logic, boundaries, error paths, normalisation | Nothing external |
| Integration | Real Postgres, real HTTP boundaries, migrations | A dedicated database |
| End-to-end | Ingest → evaluate → deliver, against a real receiver | The running app |

**The test database is a separate database, not a separate schema.** Neon's branching
makes this free. This is not a preference: in the prior work in this domain, a test
fixture truncated the same database the demo ran on, destroying demo data and then
breaking the next backfill through orphaned rows.

**Determinism.** The simulator is seeded and must produce identical output across runs and
across `PYTHONHASHSEED` values. A test asserts this. Separate named RNG streams per
concern are what makes it survive.

## CI gates

Every push and pull request runs `./scripts/verify.sh` — the same command run locally.
Nothing merges red.

| Gate | Checks | Blocks merge |
|------|--------|--------------|
| Phase | `docs/.phase` names a valid phase | yes |
| Documents | every document due by that phase is written and placeholder-free | yes |
| Attribution | no trace in tracked files, commit messages, or commit **author identity**, on any branch | yes |
| Secrets | no private key, cloud key id, or token pattern in a tracked file | yes |
| Lint | ruff | yes |
| Types | mypy | yes |
| Tests | pytest, unit + integration | yes |

**The gate must actually run in CI.** This sounds too obvious to write down. It is the
first item on the never-ship list because it is the failure that actually happened: the
prior work's `verify` target was a stub that echoed a placeholder string and re-ran lint,
and it appeared nowhere in its CI workflow. Four sprints were signed off against it, while
its own quality document condemned "a CI that can lie."

## Never-ship list

Every item is a defect that genuinely occurred in prior work in this domain, found by
reading the code rather than the documentation. Each becomes a regression test the first
time it is relevant.

**Claims that outrun the code**

1. A docstring, comment, or document asserting a guarantee the code does not provide. Any
   such claim requires a test that fails without the property. Eight separate instances
   were found in one repository.
2. Calling a mechanism "exactly-once" when it is at-least-once. An outbox with idempotency
   keys is at-least-once by design and that is correct — say so.
3. A document still presenting a superseded decision as current.
4. Claiming test coverage of something that does not exist.

**Checks that do nothing**

5. A validity check that is arithmetically incapable of failing. One "honest count, never
   `len(input)`" returned a value provably identical to `len(input)`.
6. A test asserting a range wide enough to pass regardless of the behaviour it claims to
   prove.
7. An index built for a query, where no code path issues that query.
8. Security behaviour that depends on a library default rather than an explicit argument.
   Redirects were not followed only because the HTTP client happens to default that way.

**Silence**

9. An exception caught, logged, and swallowed without rolling back the transaction — which
   poisons every later use of a long-lived session while the log shows one handled error.
10. Records dropped, capped, or skipped without a count surfaced in the API.
11. A background chain wired by convention rather than enforced at startup, so a caller
    that skips registration writes successfully and silently never alerts.

**Contradiction**

12. Two different values for the same concept in one response, derived over different
    populations.
13. A number presented without the sample size or interval behind it.

**Data honesty**

14. Simulated data presented without its provenance field. The field is non-nullable; a
    response cannot omit it.
15. A model evaluated on data it was fitted on — including partially, at a split boundary,
    without an embargo.
16. A metric or chart presented as measured when it is synthetic or hardcoded.

**Resource discipline**

17. A query loading an entire growing table with no limit.
18. Data written with no retention path.
19. An artifact written inside the package directory, which vanishes on an ephemeral
    filesystem and leaves the API reporting "unavailable" forever.
20. Redundant indexes that are exact prefixes of an existing primary key.

**Secrets**

21. A credential compared with `!=` rather than a constant-time comparison.
22. A secret as a default value in committed configuration, including a development one.

## Review gate

Every sprint ends with an adversarial review before it is called done. On a solo project
this is the substitute for a second engineer, so it is not optional and it does not get
skipped when the sprint ran long.

The reviewer reads with fresh context, cites `file:line`, and reports the command and
output behind every claim. Findings rank MUST-FIX / SHOULD-FIX / CONSIDER; a sprint with
an open MUST-FIX is not done.

**Review reads the code, not the documentation.** The prior work's documentation described
a more careful system than the one that existed. A review that had read only the docs would
have passed it.

Anything significant that review catches gets an entry in `09-LEARNING.md`: what was
missed, why it was possible to miss, and the test that now catches it.
