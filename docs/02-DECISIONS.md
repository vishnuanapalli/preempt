# Decision log

Append-only. Every consequential choice gets an entry, numbered in the order it was made.

**Never edit a past entry.** If a decision turns out wrong, add a new entry that supersedes
it and mark the old one `Superseded by D-0NN`. This log records what was believed at the
time; `01-DESIGN.md` describes the system as it is now. Rewriting history here destroys
the only evidence of how the thinking developed.

---

## D-001 — Use real Azure pricing alongside simulated AWS and GCP

- **Date:** 2026-07-28
- **Status:** Accepted

**Context**

The project has no cloud credentials and a zero-cost ceiling, so the working assumption
was that all three providers would be simulated. Checking that assumption rather than
inheriting it turned out to matter: Microsoft's Retail Prices API is documented as giving
"an unauthenticated experience," and a live call confirmed it — HTTP 200, 1,000 records,
real spot prices for `eastus`, no account and no key.

AWS and Google both require credentials and, in practice, a billing relationship. Neither
can be obtained at zero cost.

**Decision**

Ingest real Azure prices. Simulate AWS and GCP. Label the source of every row, and make
that label a non-nullable field on every response that carries a price or a prediction.

**Consequences**

The system is more credible: a third of it is genuinely real, and the part that is not
says so in the payload rather than in a footnote. It also becomes harder to build
honestly. A comparison between a measured Azure price and a simulated AWS one is not
like-for-like, and the API has to say that rather than quietly present one number. The
`mixed` provenance value exists for exactly this, and the interface must show it rather
than hide it behind a tooltip.

It also introduces a real external dependency into ingestion, with a real failure mode:
Azure can be unreachable or change its response shape. `01-DESIGN.md` handles both by
failing that provider's ingest while still committing the other two.

**Alternatives rejected**

Simulating all three would be simpler, more internally consistent, and easier to explain.
It was rejected because declining genuinely available real data in order to keep the story
tidy is the wrong trade, and because "we checked whether real data was obtainable and it
was" is a better answer to an interviewer than "we assumed it was not."

---

## D-002 — Ingest every thirty minutes

- **Date:** 2026-07-28
- **Status:** Accepted

**Context**

Neon's free plan allows 100 compute-unit-hours per project per month, roughly 400 hours at
the smallest compute size. A month is about 730 hours, and scale-to-zero after five
minutes cannot be disabled on the free plan.

A five-minute tick keeps the database permanently awake. At roughly 730 hours of wake time
against a 400-hour budget, the project's compute suspends around day sixteen — almost
certainly unattended, and most likely the night before it is needed.

**Decision**

Ingest every thirty minutes. Approximately 124 hours of wake time per month, leaving
headroom for demo traffic.

**Consequences**

Price history has thirty-minute resolution rather than five. For a chart showing trend
over ninety days this is invisible. The alerting story changes shape: an alert can be up
to thirty minutes late, so alert rules must be written about levels that persist rather
than about instantaneous spikes.

This is the clearest example of an infrastructure constraint driving a product decision,
and it is worth being able to explain: the cadence was derived from a compute budget, not
chosen by preference.

**Alternatives rejected**

Hourly is safer still (~62 hours) but makes the data feel stale in a live demo.
Five-minute matches prior work in this domain but is arithmetically impossible here.
Paying for a database was not considered — the zero-cost ceiling is a stated requirement,
not a preference.

---

## D-003 — Koyeb for the API, Neon for the database, an external scheduler

- **Date:** 2026-07-28
- **Status:** Accepted

**Context**

The demo has to be reachable and fast during an interview, at zero cost. Idle-suspension
behaviour, not RAM or CPU, is what decides this:

| Provider | Free | Idle before sleep | Cold start |
|----------|------|-------------------|------------|
| Koyeb | 1 service, 512 MB, 0.1 vCPU | 1 hour | ~5 s |
| Render | 750 hours/month | 15 minutes | 30–60 s |
| Fly.io | no free tier for new accounts (2026) | — | — |
| Oracle Always Free | real VMs, never sleeps | reclaimed when p95 CPU < 20% over 7 days | — |

**Decision**

Koyeb for the API. Neon for Postgres, with TimescaleDB. An external scheduler, not
`pg_cron`. A static frontend on a CDN, so the page itself is instant and only the first
data fetch pays the wake.

**Consequences**

A cold start of roughly five seconds is possible if nobody has touched the demo for an
hour. That is survivable, and it becomes an interface problem rather than an
infrastructure one: the frontend shows a skeleton immediately instead of a blank page or a
spinner. `06-UI-SPEC.md` owns that decision.

0.1 vCPU is genuinely small. Query work has to stay in the database rather than being
done in Python over large result sets.

Neon supports TimescaleDB but not compression. Prior work in this domain never used
compression, so nothing is lost — but retention has to be a scheduled delete rather than a
Timescale retention policy, because policy jobs need a background worker a scale-to-zero
database does not have.

**Alternatives rejected**

Render was the obvious default and is the worst fit: a 30–60 second cold start is a failed
demo. Oracle Always Free is the only genuinely always-on option, but its reclamation rule
targets exactly the profile of a low-traffic demo API. Supabase pauses free projects after
seven days of no traffic, which makes the demo's survival contingent on the scheduler
never breaking.

---

## D-004 — The pool is the unit of risk

- **Date:** 2026-07-28
- **Status:** Accepted

**Context**

Interruption risk can be modelled per machine or per pool — a machine type in one zone for
one operating system. Prior work in this domain concluded the pool, on the reasoning that
reclamations within a pool share an underlying cause (capacity pressure in that zone for
that shape) and therefore cluster rather than occurring independently.

**Decision**

The pool is the unit. It is the grain of the risk score, the primary key of the fact
tables, and the thing an alert subscribes to.

**Consequences**

This is the single hardest decision to reverse, because it is the key structure of three
hypertables. Getting it wrong means a migration of every fact row.

It also makes the product's claims narrower and more honest. "This pool has been unstable"
is a defensible statement; "this machine will be interrupted" is not.

**On the evidence, stated honestly**

The supporting figure carried into this project second-hand — that a large majority of
co-interruptions occur within a three-minute window — could **not** be verified. The paper
it was attributed to (arXiv 2604.16457, "Ding-Dong Ditch: Peeking Into Spot Instance
Availability") does exist, and does report availability modelling at F1-macro up to 0.90
across 68 instance types and 15 regions using 336,033 spot requests. The clustering
statistic specifically was not confirmed from its abstract.

The decision therefore rests on the mechanism being sound — pooled capacity is the shared
cause, so pooled outcomes are correlated — and not on a number this project can cite. If
the figure is needed in the case study, the full paper must be read first. A citation a
reviewer can check and find wrong would cost more than having no citation at all.

**Alternatives rejected**

Per-instance risk would require identity the system does not have and cannot obtain
without provisioning. Per-region risk is too coarse: it hides exactly the variation
between zones that makes the product useful.

---

## D-005 — Port the delivery engine and the prediction split; rebuild ingestion and storage

- **Date:** 2026-07-28
- **Status:** Accepted

**Context**

Substantial prior work exists in this domain: about 11,500 lines of Python, 167 test
functions, five migrations, and a 27-entry decision log. Preempt is meant to be
independent work, so what carries over needs a reason rather than a default.

Reading the prior code rather than its documentation established: the Timescale dependency
is four lines in one migration (one `CREATE EXTENSION` and three `create_hypertable`
calls), there are **zero** compression or retention-policy calls, and there are **zero**
TODO or FIXME markers in application code. The delivery engine implements the outbox
pattern with `FOR UPDATE SKIP LOCKED`, exponential backoff with jitter, dead-lettering,
HMAC signing with constant-time comparison, idempotency keys, and coalescing that reports
what it suppressed. The prediction pipeline uses a genuine three-way
train/calibrate/final-eval split.

**Decision**

| Component | Verdict | Reason |
|-----------|---------|--------|
| Alert delivery engine | Port | The correct answer to a genuinely hard problem, already found and tested |
| Prediction train/calibrate/eval split | Port | Encodes a specific, hard-won correction |
| Schema shape and hypertable choice | Port | Timescale dependency is four lines; nothing depends on compression |
| Ingestion and cadence | Rebuild | Built for a five-minute tick that is arithmetically impossible here |
| Storage strategy | Rebuild | 0.5 GB is a constraint the prior work never faced |
| Azure provider | New | No prior equivalent — prior work had no real data source |

**Consequences**

The genuinely new engineering in Preempt is the part the constraints forced: a real
external data source, a store-on-change write path, a bounded pool set derived from a row
budget, and a cadence derived from a compute budget. That is a defensible answer to "what
did you actually design here?"

Porting the delivery engine is a deliberate choice to keep a correct solution rather than
reinvent it worse. The three-way split is worth more than the code: it exists because an
earlier two-way split produced a reliability diagram that looked excellent for a purely
mechanical reason — the calibrator was fit and evaluated on the same array. That is the
kind of error worth carrying the fix for.

**Alternatives rejected**

Rebuilding everything from scratch would be more purely independent, but throwing away a
correct outbox implementation to write a worse one proves nothing. Porting everything
would leave the project shaped by constraints that no longer apply, and would mean
inheriting a five-minute cadence that suspends the database mid-month.

---
