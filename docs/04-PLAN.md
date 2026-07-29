# Preempt — build plan

Phase 4. The last document before code. Turns `01-DESIGN.md` into a sequence of sprints,
each small enough to finish, demo, and review.

## Sprint rhythm

Every sprint ends the same way, and the order is not negotiable:

1. All stories meet the Definition of Done in `03-QUALITY.md`
2. `./scripts/verify.sh` passes, output recorded
3. Deployed — the change is live, not just green locally
4. Demo — the thing actually runs and is shown working
5. Adversarial review; MUST-FIX items resolved
6. `docs/.phase` bumped if the sprint completed a phase
7. **Hard stop.** The next sprint does not start without an explicit go-ahead.

## Deploy first, not last

The template treats deployment as phase 7. Preempt deploys a walking skeleton in **Sprint
0** instead, and every sprint after it deploys again.

The reason is specific to this project. The largest unknowns are all free-tier behaviours
that only appear in production: how long a cold start really takes, how fast the compute
budget actually burns, whether connection limits bite under a scheduler, whether the
scheduled job fires on time. Discovering any of those in the final sprint would invalidate
design decisions that everything else was built on.

So a health endpoint goes live on the real infrastructure before any feature exists. The
runbook is still written at phase 7, because that is when there is something real to
operate — but the thing being operated has been live since the first week.

## Sprints

### Sprint 0 — Foundations and a live skeleton

**Goal:** the real infrastructure is running, the gate is real, and every later sprint has
somewhere to land.

- [ ] Python 3.12 + FastAPI + SQLAlchemy + Alembic, managed with uv; recorded in `02-DECISIONS.md`
- [ ] `scripts/verify.sh` stack section filled in — ruff, mypy, pytest — and passing
- [ ] CI setup block uncommented; the gate runs on every push
- [ ] Neon project created; a branch used as the dedicated test database
- [ ] Baseline migration applied; reversibility established by a harness that compares the
      schema before and after, not by the round trip exiting 0 — see S-002 and D-015
- [ ] Health endpoint reporting liveness and ingestion freshness
- [ ] Deployed to Koyeb; the health endpoint answers over the public internet
- [ ] External uptime monitor pointed at it
- [ ] `.env.example` lists every variable the app reads
- [ ] Seed script skeleton — the file exists and runs, even if it seeds nothing yet

**Demo:** a public URL returns a health response; CI is green; the uptime monitor is
reporting.

**Measure and record, because these numbers were assumed in `01-DESIGN.md` and must now be
checked:** observed cold-start duration after an hour idle, and CU-hours consumed in the
first 24 hours. If either contradicts the design, that is an ADR, not a silent adjustment.

### Sprint 1 — Data foundation

**Goal:** real and simulated prices land in the database, with provenance, at 30-minute
cadence.

- [ ] Core schema: catalog, pool, and three hypertables
- [ ] Market simulator — port the pure generator modules, including per-concern named RNG streams
- [ ] Determinism test: identical output across runs and across `PYTHONHASHSEED` values
- [ ] Azure provider: fetch, paginate, normalise, extract spot meters
- [ ] Store-on-change writer with idempotent upsert; a concurrency test with parallel writers
- [ ] Provenance recorded per row; a test asserts it can never be null
- [ ] Retention: scheduled delete beyond 90 days
- [ ] Backfill producing 90 days of history within the row budget
- [ ] Pool set bounded at 500; a test fails if the tracked set exceeds it

**Demo:** the database holds real Azure prices next to simulated AWS and GCP, each
labelled; row count is inside budget.

**Advances `docs/.phase` to:** 5

### Sprint 2 — Query API

**Goal:** the questions in the PRD are answerable over HTTP.

- [ ] Search, compare, history, provider summary
- [ ] Cross-provider normalisation, with the comparison basis stated in the response
- [ ] Provenance on every price-bearing response; `mixed` where a comparison spans sources
- [ ] One error shape across every route
- [ ] API key auth on writes; rate limiting with the single-instance assertion from D-007
- [ ] OpenAPI document generated; TypeScript types generated from it with a CI drift gate

**Demo:** a `curl` answers "cheapest 8 vCPU / 32 GB machine across three clouds," and the
response says which numbers are real.

### Sprint 3 — Alerts

**Goal:** an alert fires, is signed, and arrives — and survives the receiver being down.

- [ ] Subscription model, typed rules, CRUD behind an API key
- [ ] Evaluation on the ingest event; crossing detection, not polling
- [ ] Listener registration enforced at startup per D-008, with a test that ingest fails loudly without it
- [ ] Outbox with `FOR UPDATE SKIP LOCKED`; claim commits before any network call
- [ ] Retry with capped exponential backoff and jitter; dead-letter at the cap
- [ ] Idempotency key enforced by a database constraint, not only in application code
- [ ] HMAC signing, constant-time verification
- [ ] SSRF guard at registration and again at delivery; `follow_redirects=False` set **explicitly**
- [ ] Coalescing, with the suppressed count exposed in the API
- [ ] Delivery dashboard and a test-fire endpoint
- [ ] End-to-end test against a real local receiver

**Demo:** register a rule, watch it fire, take the receiver down and watch it retry and
then dead-letter.

**Highest blast radius of any sprint.** This is the one that gets the security review.

### Sprint 4 — Prediction and the honesty layer

**Goal:** a risk number that reports its own accuracy.

- [ ] Feature pipeline over pool identity and capacity signals
- [ ] Label: does the pool stay available over the horizon
- [ ] Three-way temporal split **with the embargo from D-006**; a test fails if the gap is absent
- [ ] Logistic baseline with calibration fitted only on the calibration split
- [ ] Reliability diagram and Brier score computed only on the final evaluation split
- [ ] Regression test asserting no bin is bit-identical — the tautology guard
- [ ] Risk exposed per pool with interval and sample size
- [ ] Honesty layer: signal availability per provider, and what is not known
- [ ] Decide the `is_business_hours` circularity flagged in D-006

**Demo:** the calibration endpoint returns a diagram whose predicted and observed values
differ, as they should on genuinely held-out data.

### Sprint 5 — Interface

**Goal:** a frontend built in one pass.

- [ ] `06-UI-SPEC.md` filled in completely against the running API, with the readiness check satisfied
- [ ] Open questions in that document closed **before** any UI code is written
- [ ] Frontend built from the spec
- [ ] Cold-start experience handled deliberately — skeleton, not a blank page
- [ ] Accessibility floor checked, contrast ratios measured and recorded

**Advances `docs/.phase` to:** 6

### Sprint 6 — Hardening and release

- [ ] `07-RUNBOOK.md` written and rehearsed by actually following it
- [ ] Seed rebuild proven from an empty database
- [ ] Free-tier keep-alive behaviour recorded from observation, not assumption
- [ ] `08-CASE-STUDY.md`
- [ ] Repository made public

**Advances `docs/.phase` to:** 8

## Sequencing

Schema precedes writers; writers precede readers; readers precede the interface. Alerts
need an ingest event to hang off, so they follow ingestion. Prediction needs a corpus, so
it follows backfill.

The one deliberate inversion is deployment, which comes first for the reasons above.

## Risks

| Risk | Early signal | Response |
|------|--------------|----------|
| CU-hours burn faster than the estimate | Sprint 0 measurement | Lengthen cadence to hourly; the design already shows it fits |
| Cold start worse than ~5s | Sprint 0 measurement | Interface absorbs it, or move to a provider with a longer idle window |
| Azure changes its response shape mid-build | Normalisation test fails | Simulated providers keep working; that provider degrades alone |
| Scheduled job unreliable or disabled by inactivity | Freshness ages in `/health` | Switch scheduler; the 30-minute cadence tolerates delay |
| Ported code carries an assumption from a system that was never hosted | Review | D-007 is the general fix: assert assumptions, do not inherit justifications |

## Deferred

- MCP server. The prior implementation must be rebuilt regardless, and it is not on the
  path to any success criterion. Revisit after Sprint 4.
- Gradient-boosted model. Logistic plus honest calibration is the deliverable; a better
  score on simulated data is not.
- Cross-provider risk comparison. The providers' signals are not equivalent, and averaging
  them away would violate the honesty rule the project is built on.
