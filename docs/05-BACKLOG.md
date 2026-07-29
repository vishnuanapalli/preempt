# Preempt — backlog

Every story, prioritised. `04-PLAN.md` says which sprint each lands in; this file says what
"done" means for it.

Sprints 0 and 1 are specified in full because they start next. Later sprints carry their
goal and their non-obvious criteria, and are expanded at their own kickoff — writing
detailed acceptance criteria for work five sprints out produces fiction, and D-020 in the
prior work exists precisely because stories written too early assume state that does not
exist yet.

## Priority

- **MUST** — the project does not ship without it.
- **SHOULD** — real value, but the project stands without it.
- **COULD** — worth doing if time allows.
- **WON'T** — decided against, kept visible with the reason.

Acceptance criteria are checkable by a test or by direct inspection. "Works correctly" is
not a criterion; "returns 422 with an `invalid_field` code when `region` is unsupported" is.

---

## Sprint 0 — Foundations and a live skeleton

### S-001 — The gate is real and runs in CI
**MUST** · no dependencies

So that no later story can be signed off against a stub, which is the first item on the
never-ship list.

- [ ] `scripts/verify.sh` section 3 runs ruff, mypy, and pytest
- [ ] The CI workflow's toolchain block is uncommented and the gate runs on every push
- [ ] Deliberately breaking lint turns CI red; this is verified once, by doing it
- [ ] The run's output is recorded in the sprint demo

### S-002 — Database provisioned, migrations reversible
**MUST** · depends on S-001

- [ ] Neon project created; connection string in `.env.example` as a placeholder only
- [ ] A Neon branch serves as the dedicated test database; tests never touch the primary
- [ ] Baseline migration applies to an empty database
- [ ] `alembic downgrade base` then `upgrade head` succeeds against a real database
- [ ] A test asserts the test database URL differs from the application's

### S-003 — Health endpoint reporting freshness
**MUST** · depends on S-002

- [ ] `GET /api/v1/health` returns liveness, database reachability, and the age of the newest observation
- [ ] Freshness is null, not zero, when no observation exists
- [ ] Returns 503 when the database is unreachable, with the standard error shape

### S-004 — Live on the public internet
**MUST** · depends on S-003

- [x] Deployed to Vercel; health endpoint answers over HTTPS from outside the network
      — `curl -si https://preempt-tau.vercel.app/api/v1/health` → `HTTP/2 200`, `43673c8`.
      Platform was Koyeb when this was written; D-010 replaced it with Vercel.
- [ ] External uptime monitor polls it every 15 minutes — poll `/health` only, never
      `/ready`, which costs compute budget (D-009)
- [ ] Secrets set as platform environment variables; none in the repository.
      `PREEMPT_ENVIRONMENT` is set; `PREEMPT_DATABASE_URL` is not, and is waived in
      `docs/SERVICES.md` until Sprint 1. Current state lives in `audit/PREFLIGHT.txt` —
      deliberately not restated here, because a pasted response is stale the moment the
      next deployment lands.
- [ ] **Measured and recorded:** cold-start duration after one hour idle
- [ ] **Measured and recorded:** CU-hours consumed in the first 24 hours, extrapolated to a month
- [ ] If either measurement contradicts `01-DESIGN.md`, an ADR is written — not a silent adjustment

### S-005 — Seed script exists and runs
**MUST** · depends on S-002 · **DEFERRED into Sprint 1**

Deferred 2026-07-29. The acceptance criterion is "runs against an empty database without
error", but Sprint 0 has no tables — the baseline migration creates none. A seed script
written now would either seed nothing, or invent a schema that Sprint 1 is supposed to
design, which is the "do not invent state to satisfy acceptance criteria" rule in
`CLAUDE.md`. It moves to Sprint 1 alongside the schema it seeds, and Sprint 0 closes
without it.

- [ ] `scripts/seed.py` runs against an empty database without error
- [ ] Documented in the runbook stub as the recovery path
- [ ] Idempotent: running twice leaves the same state

---

## Sprint 1 — Data foundation

### S-010 — Core schema
**MUST**

- [ ] Catalog, pool, and three hypertables per `01-DESIGN.md`
- [ ] `observed_at` is part of every hypertable's primary key
- [ ] No index that is an exact prefix of its own primary key — never-ship #20
- [ ] Migration reversible against a real database

### S-011 — Market simulator, ported
**MUST** · depends on S-010

- [ ] Pure generator modules ported with no database imports
- [ ] Separate named RNG streams per concern
- [ ] Identical output across two runs with the same seed
- [ ] Identical output across two different `PYTHONHASHSEED` values — the test that made determinism survive adversarial review before

### S-012 — Azure provider
**MUST** · depends on S-010

- [ ] Fetches from the public endpoint with no credentials
- [ ] Follows pagination to completion
- [ ] Extracts only spot meters
- [ ] Normalises into the shared observation shape
- [ ] Returns a typed error, not a partial result, on an unexpected response shape
- [ ] Unit tests run against a recorded payload, never the live API

### S-013 — Store-on-change writer
**MUST** · depends on S-011, S-012

- [ ] Writes a row only when the price differs from the last recorded for that pool
- [ ] Unchanged observation updates `pool.last_seen` and writes no history row
- [ ] Idempotent upsert; re-running a tick creates no duplicates
- [ ] A concurrency test with parallel writers produces no lost update
- [ ] Reported counts are derived from the database result, and a test proves the count can differ from the input length — never-ship #5

### S-014 — Provenance is structural
**MUST** · depends on S-013

- [ ] Every observation row carries its source
- [ ] The column is non-nullable at the database level, not only in the model
- [ ] A test attempting to insert without provenance fails

### S-015 — Retention and the row budget
**MUST** · depends on S-013

- [ ] Scheduled delete removes observations older than 90 days
- [ ] Tracked pools capped at 500; a test fails if the set exceeds it
- [ ] After a 90-day backfill, measured storage is recorded and compared against the 0.5 GB limit

### S-016 — Backfill
**MUST** · depends on S-015

- [ ] Produces 90 days of history using the same generator as the live tick
- [ ] Resumable; interrupting and restarting does not duplicate or skip
- [ ] Completes inside the compute budget, with the cost measured

---

## Sprint 2 — Query API

Goal: the PRD's questions answerable over HTTP. Non-obvious criteria:

- Comparison states its basis in the response, not in documentation
- A comparison spanning real and simulated sources is labelled `mixed`
- One error shape across every route, defined once
- Generated TypeScript types have a CI drift gate that fails on a stale commit
- Pagination is stable under concurrent upserts, or the response says it is not — never-ship #15

## Sprint 3 — Alerts

Goal: an alert fires, is signed, arrives, and survives a dead receiver. Non-obvious criteria:

- The outbox claim commits **before** any network call
- Lease duration exceeds the HTTP timeout, and a test asserts the relationship rather than the constants
- Idempotency enforced by a database constraint
- `follow_redirects=False` passed **explicitly**, with a test that fails if it is removed — never-ship #8
- Delivery described as at-least-once everywhere, never exactly-once — never-ship #2
- Ingest with no registered listener fails loudly — D-008
- The evaluation query uses an index, proven by an execution plan, not by a docstring — never-ship #7

## Sprint 4 — Prediction

Goal: a risk number that reports its own accuracy. Non-obvious criteria:

- Embargo of one label horizon at each split boundary, with a test that fails without it — D-006
- Calibration fitted only on the calibration split
- All reported metrics computed only on the final split
- A regression test asserting no reliability bin is bit-identical
- Every prediction response carries interval and sample size — never-ship #13
- The `is_business_hours` circularity resolved and recorded

## Sprint 5 — Interface

Goal: built in one pass from a completed specification. Non-obvious criteria:

- `06-UI-SPEC.md` has **zero** open questions before any UI code is written
- Contrast ratios measured and recorded, not asserted
- Cold start shows a skeleton, not a blank page or a spinner

## Sprint 6 — Hardening and release

Goal: operable by someone reading only the runbook. Non-obvious criteria:

- The runbook is rehearsed by following it literally, from a cold start
- Seed rebuild proven from an empty database
- Keep-alive behaviour recorded from observation

---

## Won't do

| Item | Why not |
|------|---------|
| MCP server | Must be rebuilt regardless, and not on the path to any success criterion. Revisit after Sprint 4. |
| Gradient-boosted model | A better score on simulated data is not a better project. Logistic plus honest calibration is the deliverable. |
| Real AWS or GCP data | Requires credentials and a billing relationship. Out of scope in the PRD, and the reason the provenance field exists. |
| Cross-provider risk comparison | The signals are not equivalent. Averaging them into one number would violate the honesty rule the project rests on. |
| User accounts | API keys authenticate writes. Sign-up, billing, and multi-tenancy are a different product. |
