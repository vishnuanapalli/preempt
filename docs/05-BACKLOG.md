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
- [x] A reversibility harness runs the whole migration chain against the local test database
      — the `db-test` container on 5434, not the Neon branch the criterion above still names
      — reversing and re-applying it, and reports any schema object the reverse failed to
      restore. Proven able to fail by two deliberately broken migrations: one that drops
      nothing on downgrade, one that raises on upgrade. `api/tests/test_reversibility.py`,
      evidence in `audit/REVERSIBILITY.txt`, rationale in D-015 and D-016.
      **Corrected 2026-07-29.** This criterion claimed per-migration stepping, three sabotage
      shapes and a twenty-two-case mutation matrix for several hours after all three were
      deleted at `3bfb297` (D-016, ledger R9/R10). STATUS and the audit file were corrected in
      the same pass and this was missed — the one document of the three that asserts *done*.
      **It covers real schema as of S-010.** `covered` and `head_classes` are each bounded
      from *both* sides — a floor derived from the model table count, and an exact-equality
      assertion on a hand-built snapshot — because a one-sided bound is satisfied by a
      constant. Review found exactly that, twice: first on `covered`, then on `head_classes`
      after it was added to close the first. Both counterweights are verified by reverting
      them and requiring the suite to go red.
      The criterion this replaces — "`alembic downgrade base` then `upgrade head` succeeds
      against a real database" — was satisfied by a migration whose `upgrade()` and
      `downgrade()` are both `pass`, and was reported as evidence in the Sprint 0 demo.
- [ ] A test asserts the test database URL differs from the application's

### S-003 — Health endpoint reporting freshness
**MUST** · depends on S-002

- [ ] `GET /api/v1/health` returns liveness, database reachability, and the age of the newest observation
- [ ] Freshness is null, not zero, when no observation exists
- [ ] Returns 503 when the database is unreachable. **The error *shape* is deferred to
      Sprint 2**, where `S-020` defines one shape for every route — this criterion cannot
      be met before the thing it references exists, which is the same defect S-005 was
      deferred for and the case D-016 rule 1 now covers. Until then: 503 with a body, and
      the shape is settled once, in one place
- [ ] `/ready` reports `not_configured` rather than `ok` while no database is configured.
      A readiness probe that claims ok before it is ready is indistinguishable from a
      healthy one with no data yet

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
- [ ] **Measured and recorded:** cold-start duration after one hour idle.
      **Partial — attempted, not established.** `audit/COLD-START.txt` records the
      invocation and the numbers. First request after a 65-minute idle window returned
      HTTP 200 in 400 ms; a warm request straight after took 231 ms.
      The box stays unticked because the criterion says *cold start* and what was measured
      is first-request latency. Nothing proves the instance was evicted, and the idle
      window only means "no request from this client" — the URL is public. A 169 ms
      cold/warm gap is small for Python, and D-010's predicted 1–2 s being missed by
      2.5–5× in the *fast* direction is better read as the experiment not having run than
      as a fast cold start. To close this, read Vercel's runtime logs for the cold-start
      flag on the request id rather than inferring from latency.
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

- [x] `scripts/seed.py` runs against an empty database without error — seeded the test
      database for real: `20 inserted, 0 already present, 0 underivable`, across three providers
- [x] Documented in `docs/07-RUNBOOK.md` as the recovery path, including what it does **not**
      restore: `price_metric` history comes from ingestion ticks and is gone for good
- [x] Idempotent: running twice leaves the same state. By construction rather than by checking
      first — `ON CONFLICT DO NOTHING` on the natural key has no read-then-write window. Pinned
      by `test_seeding_twice_leaves_the_same_rows` against the real database
- [x] **Specs are derived, and every row says so.** Azure's price feed carries no hardware
      description (D-019), so `app/ingest/catalog.py` derives vCPU and memory from the
      documented size naming convention and **refuses** what the convention cannot express —
      GPU and high-memory families return `None` rather than a plausible default. Written as
      inspectable code rather than a table of asserted numbers, because a derivation can be read
      and disagreed with; ~40 numbers typed in from memory could not be told from invented ones

---

## Sprint 1 — Data foundation

### S-010 — Core schema
**MUST**

- [x] Catalog, pool, and three hypertables per `01-DESIGN.md` — `f317a85b9b46`. Verified in
      the database, not from the migration: `timescaledb_information.hypertables` lists
      `capacity_metric`, `interruption_event`, `price_metric`
- [x] `observed_at` is part of every hypertable's primary key. Two reasons that agree —
      TimescaleDB requires the partitioning column in any unique index, and per-pool history
      over a window is the primary read
- [x] No index that is an exact prefix of its own primary key — never-ship #20. No index is
      declared for the `(pool_id, observed_at)` pattern precisely because the primary key
      already serves it; that is how this defect arrives
- [x] `api/tests/test_reversibility.py` reports non-zero coverage and passes. **The strict
      xfail fired as designed** — it failed the moment real tables landed, which was the
      signal to delete it, and it is gone. Counts deliberately not pasted here; they were
      stale within two commits every previous time
- [x] The harness's TimescaleDB blind spot is settled: chunks are **not** extension-owned
      (no `pg_depend` row with `deptype = 'e'`) and `_timescaledb_internal` is not caught by
      the `pg_%` filter, so the harness *does* see chunks — a downgrade orphaning one would be
      reported. Established by creating a hypertable and querying `pg_depend`, not reasoned
      about. Also learned: timescaledb is installed into `public`, so `DROP SCHEMA public
      CASCADE` is never a safe reset here
- [ ] Provenance recorded per row; a test asserts it can never be null — `source` is
      non-nullable with a database CHECK on every fact table, but no test yet proves the
      constraint fires. S-014

### S-011 — Market simulator, ported
**MUST** · depends on S-010

- [x] Pure generator modules with no database imports — `app/providers/simulated.py` imports
      only `hashlib`, `datetime`, `decimal` and the shared observation shape
- [x] Separate named RNG streams per concern. Price, capacity and interruption each key on
      their own stream name, so adding a draw cannot shift an existing one — one shared
      generator would mean a new capacity draw silently changed every price after it
- [x] Identical output across two runs with the same seed
- [x] Identical output across two different `PYTHONHASHSEED` values — **the test D-005 says made
      determinism survive adversarial review.** It runs real subprocesses under `0`, `12345` and
      `random`, because the defect it guards against lives only across a process boundary:
      Python salts `hash()` per interpreter, so a generator seeded from it is perfectly
      deterministic within one process and different on every run. Keys are hashed with
      **blake2b** instead. A companion test demonstrates that `hash()` really does differ under
      those seeds in this environment, so the guard is shown able to fail rather than assumed
- [x] Simulated everywhere it surfaces: `source="simulated"` on every row, and types named
      `sim.*` so a name alone gives it away even if a caller drops the field. The simulator takes
      the catalog rather than inventing types, so no row exists that no catalog entry explains

### S-012 — Azure provider
**MUST** · depends on S-010

- [x] Fetches from the public endpoint with no credentials — `azure:retail-prices` in
      `preflight.sh` records `1000 items for eastus, unauthenticated`
- [x] Follows pagination to completion. `$top` is **ignored** by the endpoint (a request for 5
      returned 1000), so `NextPageLink` is the only page control; a two-page fixture pins it,
      and a link that loops raises rather than returning what it had
- [x] Extracts only spot meters — client-side on `skuName`, because OData `contains()` could
      not be verified: the request testing it is the one that hit 429. Building on an
      unverified filter is how a provider silently returns nothing
- [x] Normalises into the shared observation shape (`app/providers/base.py`), with `source`
      non-optional. Two approximations recorded rather than hidden: the retail API prices a
      region not a zone (`REGION_WIDE`), and OS is inferred from a display string, so RHEL and
      SUSE will read as `linux`
- [x] Returns a typed error, not a partial result. `ProviderUnavailable` for 429 and transport
      failures (retryable), `UnexpectedResponse` for a shape it cannot honestly interpret. A
      missing price raises rather than defaulting to zero, which would read as a free machine
      and win every comparison
- [x] Unit tests run against a recorded payload, never the live API — 15 tests in 0.05s.
      **Not a preference:** the endpoint returned HTTP 429 on a second request seconds after
      the first, and preflight reproduced that while this was being built. Fixtures are real
      response bytes, trimmed to six items, never invented

### S-013 — Store-on-change writer
**MUST** · depends on S-011, S-012

- [x] Writes a row only when the price differs from the last recorded for that pool
- [x] Unchanged observation updates `pool.last_seen` and writes no history row. `GREATEST`, so
      a retried or delayed tick cannot drag `last_seen` backwards and make live ingestion look
      stalled — pinned by its own test
- [x] Idempotent upsert; re-running a tick creates no duplicates
- [x] A concurrency test with parallel writers produces no lost update. **It found a real
      deadlock:** the pool upsert holds a row lock while the first insert into a hypertable
      takes a table-level lock to create its chunk, so three writers on one new pool
      deadlocked. Each observation now writes inside a `SAVEPOINT` and retries on SQLSTATE
      `40P01`/`40001`, which is sound because the writes are idempotent (D-019). Stated in
      D-019 rather than hidden: the deadlock is nondeterministic, so the retry branch is
      exercised opportunistically, not on demand
- [x] Reported counts are derived from the database result, and a test proves the count can
      differ from the input length — never-ship #5. `prices_written` is what
      `INSERT ... RETURNING` produced; `test_the_written_count_differs_from_the_input_length`
      feeds three observations and asserts one write. `WriteResult` also refuses to exist
      unless the buckets sum to the input, so a count cannot go quietly missing
- [ ] **Opened by this story:** prices for an un-catalogued instance type are dropped and
      counted, because Azure's price feed carries no vcpu or memory and inventing them is
      forbidden (D-019). The catalog must be seeded — S-005, already deferred into Sprint 1,
      now with a second reason to exist

### S-014 — Provenance is structural
**MUST** · depends on S-013

- [x] Every observation row carries its source — on all three fact tables, not just
      `price_metric`. The table list is read from the models, so a fourth fact table is covered
      the day it is added rather than the day someone remembers
- [x] The column is non-nullable **at the database level**, verified by reading
      `information_schema.columns` rather than by trusting the model. `nullable=False` in
      SQLAlchemy and `NOT NULL` in Postgres are different facts: the first is a promise this
      application makes, only the second survives a migration or a psql session
- [x] A test attempting to insert without provenance fails, in raw SQL that goes around the
      application entirely. Four shapes, because non-null alone is not enough: column omitted,
      explicit `NULL`, an unrecognised value like `'probably real'` — which would otherwise join
      the measured rows in any query filtering on known values — and, on the other side, both
      valid sources accepted. That last one is what distinguishes a correctly strict constraint
      from one that rejects everything and would pass all three negative tests

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
- Ingest fails loudly when the outbox cannot be written — **D-012**, which replaced
  D-008's registered-listener precondition once there was no long-lived process to
  register with
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
