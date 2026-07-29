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
- **Status:** Accepted. **Hosting half superseded by D-010** — Koyeb is not the platform; Vercel is.

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

## D-006 — Embargo samples at every split boundary

- **Date:** 2026-07-28
- **Status:** Accepted. Refines D-005, which said the prediction split ports as-is.

**Context**

A closer read of the prior pipeline found a leak its own correction did not catch. The
earlier fix replaced a two-way split with a genuine three-way train / calibrate / evaluate
split, which removed the tautology of fitting and grading a calibrator on the same array.

But the splits are bare timestamp cuts, and the label looks forward six hours. A sample
taken one minute before a boundary has a label determined by events that fall inside the
next partition. The training set therefore contains a small amount of information about
the evaluation period. The prior code's comment claims a temporal split "avoids leakage by
construction" — it avoids leakage from shuffling, not forward-label leakage at the edge.

The magnitude is small: roughly 960 of about 159,000 samples, near 0.6%.

**Decision**

Drop every sample within one label horizon of each split boundary. Assert the embargo in a
test that fails if the gap is absent.

**Consequences**

A slightly smaller training set, and a number that is honestly earned. Six-tenths of a
percent will not move the Brier score meaningfully, which is exactly why it is worth
fixing now: nobody would notice it later, and a leak nobody notices is one that quietly
survives into the case study.

The wider lesson matters more than the fix. A correction can be real, documented, and
still incomplete. "We found and fixed the calibration tautology" was true, and the
pipeline still leaked at the boundary.

**Also noted, not yet decided**

One model feature — whether an observation falls in business hours — is also a knob the
simulator was given. The model partly learns a dial its own generator was handed. On
simulated data this is circular by construction. It needs either removing from the feature
set or disclosing explicitly in the honesty layer; that decision belongs with the
prediction sprint.

---

## D-007 — Single-instance assumptions are documented and asserted, not assumed

- **Date:** 2026-07-28
- **Status:** Accepted. **Mechanism superseded by D-012** (amended by D-010). The principle — assert the assumption rather than imply it — still stands; the single-instance assertion does not.

**Context**

The prior work put rate limiting in process memory and justified it explicitly by a
decision that the system would never be hosted. Preempt is hosted, so that justification
no longer exists.

In-process state is still *correct* here, because the free tier allows exactly one
instance. But it is correct by accident of a plan limit rather than by design, and nothing
prevents a future second worker from silently breaking it. The same applies to any
in-process event bus.

**Decision**

Keep in-process state, and make the assumption explicit and testable rather than implied.
The service asserts a single instance at startup and refuses to run more than one worker.
Any component holding cross-request state in memory carries a comment naming this decision.

**Consequences**

Honest, and answerable. "What breaks at scale?" has a real answer: the rate limiter and the
event bus both assume one process, the service refuses to start a second, and the fix is a
shared store. That is a better interview answer than discovering the assumption live.

The failure this prevents is specific. Inheriting a justification along with the code it
justified — where the justification is no longer true — is how a system acquires
undocumented assumptions.

---

## D-008 — Ingestion publishes an event; the scheduler cannot skip it

- **Date:** 2026-07-28
- **Status:** Accepted. **Mechanism superseded by D-012** (amended by D-010). The principle — fail loudly rather than silently — still stands; the in-process bus and startup listener precondition do not.

**Context**

In the prior work the entire chain — ingest, then evaluate alerts, then score risk — fired
inside the batch-write function via an in-process event bus, with listeners registered at
application startup. That is fine for a long-running process.

Preempt moves ingestion to an external scheduler. If the ingest path is ever invoked
through a route that has not registered its listeners, writes succeed and alerts silently
never fire. Nothing errors; the system simply stops alerting, and the only symptom is an
alert that does not arrive — which nobody notices until they need it.

**Decision**

Ingestion publishes an event, and listener registration is a startup precondition rather
than a convention. The application refuses to serve if the expected listeners are not
registered, and a test asserts that an ingest with no registered listener fails loudly
instead of quietly succeeding.

**Consequences**

One more startup check, and one silent-failure mode removed. This is the failure class the
quality bar calls out: something that looks like it worked, reports success, and did
nothing.

**Alternatives rejected**

Calling the alert evaluator directly from the ingestion path removes the trap but couples
the writer to the alerts package, which is the coupling the event bus exists to avoid.
Keeping the convention and documenting it was rejected because the prior work already
documented conventions it did not enforce, and this is exactly the resulting failure.

---

## D-009 — Liveness and readiness are separate endpoints

- **Date:** 2026-07-28
- **Status:** Accepted. Corrects an arithmetic error in `01-DESIGN.md`.

**Context**

The design derived an ingest cadence from a compute budget: Neon allows about 400 hours of
compute a month, a 30-minute tick keeps the database awake roughly 122 hours, so there is
comfortable headroom.

That calculation counted only the scheduler. The same document's observability section
specifies an external uptime monitor polling `/health` every fifteen minutes. The database
scale-to-zeros after five minutes and cannot be configured otherwise, so every poll that
touches it holds it awake for a five-minute minimum. Fifteen-minute polling is therefore a
one-third duty cycle on its own.

Recomputed as a union with the tick rather than in isolation:

| Configuration | Awake hours per month | Headroom against 400 |
|---|---|---|
| Ingest tick only — as the design claimed | 122 | 278 |
| Tick + 15-minute monitor reading the database | 243 | 157 |
| Tick + hourly deep check | 122 | 278 |

Two sections of the same document were incompatible. The row-size derivation in the same
section was checked at the same time and holds: 98 bytes counted properly, against 100
assumed.

**Decision**

Split the endpoint. `/health` reports liveness and touches nothing, so the uptime monitor
can poll it as often as it likes at no cost. `/ready` reads the database and reports
freshness, and is polled hourly — which falls inside wake windows the tick already pays
for, making its marginal cost approximately zero.

A test asserts `/health` exposes no database-backed field. The comment explaining the
constraint is not the enforcement; the test is.

**Consequences**

Detection of a suspended service stays at fifteen minutes. Detection of stalled ingestion
drops to an hour, which is acceptable when the tick itself is thirty minutes.

The wider lesson is the reason this entry exists at all. The error was not a wrong number,
it was a number computed over an incomplete set of contributors — the estimate counted the
thing being designed and ignored the monitoring built to watch it. Any budget derived from
one component's behaviour should be recomputed as a union across everything that touches
the resource.

**Alternatives rejected**

Polling the combined endpoint hourly would have satisfied the budget with one endpoint, at
the cost of taking an hour to notice the service was down — which is the thing the monitor
exists to catch quickly.


## D-010 — Vercel, and the consequences of going serverless

- **Date:** 2026-07-28
- **Status:** Accepted. Supersedes the hosting half of D-003; amends D-007 and D-008.

**Context**

D-003 chose Koyeb for a long-running process. Koyeb did not work in practice, and the
alternatives are worse: Render sleeps after fifteen minutes with a thirty-to-sixty second
cold start, Fly.io no longer has a free tier for new accounts, and Oracle Always Free
reclaims instances whose CPU stays below twenty percent — the exact profile of a demo API.

Vercel supports Python and FastAPI on its free plan, cold-starts in one to two seconds
rather than thirty to sixty, and also hosts the frontend, so the project has one platform
instead of two. Netlify was rejected: its Python support is not first-class.

**Decision**

Deploy the API to Vercel as serverless functions. Schedule the ingest tick with GitHub
Actions cron rather than Vercel Cron, whose free-plan frequency is too restricted for a
thirty-minute cadence.

**Consequences — the part that matters**

Serverless means no long-running process and many concurrent instances. Two earlier
decisions assumed the opposite and must change:

- **D-007 (in-process rate limiting) no longer works.** There is no "in process" to hold
  state in; each instance has its own memory, so a limit would silently permit N times
  what it claims. Rate limiting moves to the database. The startup assertion D-007
  describes becomes meaningless and is replaced by the state simply not living in memory.
- **D-008 (in-process event bus) no longer works.** Nothing persists between requests to
  host it. Ingestion writes to the outbox in the same transaction as the observation, and
  the delivery worker runs as a scheduled invocation rather than a background task.

Writing the outbox row inside the ingest transaction is a genuine improvement, not a
workaround: an alert can no longer be lost between "observation committed" and "listener
notified", which was the failure mode D-008 was written to prevent by other means.

Connection handling gets harder. Many short-lived instances against a database that
scale-to-zeros makes pooling essential — the pooled Neon endpoint is now mandatory rather
than merely preferred, and `statement_cache_size=0` becomes load-bearing.

**Alternatives rejected**

Continuing to hunt for free always-on compute. Every option was checked and each fails on
a specific number, not on taste. Accepting serverless and designing for it honestly is
better than a long-running process on a host that suspends, reclaims, or bills.

---

## D-011 — The process record is part of the gate

**Decision.** External dependencies are inventoried in `docs/SERVICES.md` and probed by
`scripts/preflight.sh` before any code depends on them; process cost is recorded in
`docs/10-FRICTION.md`. Section 4 of `scripts/verify.sh` enforces that these exist. A
change to the gate is itself a decision and gets an entry here.

**Why.** Two failures in Sprint 0 shared a cause. Three deployments were spent on a 404
that a local build exposed in seconds, and three dependencies — CLI auth state, a `uv`
version floor, a connection string — were each discovered while the work was already
blocked. Nothing required the external surface to be proven before it was depended on.

**Consequences.** Preflight is due by phase 2, so a project cannot reach implementation
with unprobed dependencies. The gate stays offline and deterministic: it checks the
artifacts exist, never runs the network probes, and never judges freshness. Network checks
in a Stop hook would make it slow and flaky, and a flaky gate gets switched off — which is
worse than no gate. Freshness and probe *quality* belong to `work-breaker` and
`retro-scribe` at phase boundaries.

**What this entry exists to correct.** The system above was built and shipped in `50c8631`
with no entry here, which `retro-scribe` caught on its first run: `grep` for
"preflight|SERVICES|friction" in this file returned zero while the definition of "done"
had already changed for this project and every future one. Process changes are precisely
the ones nobody logs and everyone inherits.

**Not adopted.** A gate check failing when `scripts/verify.sh` changes without this file
changing. It is cheap and deterministic enough to fit section 4's constraints, but it was
not built or tested here, and shipping an untested gate rule is the defect this decision
exists to prevent. Recorded as a proposal in `~/.claude/PROCESS-LEDGER.md`.

---

## D-012 — Serverless replaces the mechanisms of D-007 and D-008; their principles stand

- **Date:** 2026-07-29
- **Status:** Accepted
- **Supersedes:** the *mechanisms* of D-007 and D-008. Their reasoning is untouched and
  still governs. Written as a separate entry because the log is append-only.

**Context**

D-007 and D-008 were both written for a long-running process. D-010 chose Vercel, and
neither survives that choice intact.

D-007 kept rate-limiting state in process memory, justified by the free tier allowing
exactly one instance, and made that assumption safe by asserting it at startup — the
service refuses to run a second worker. Under serverless there is no instance to count.
Concurrent invocations each get their own memory, and a "refuse to start a second worker"
assertion is not merely useless: it is actively misleading, because it would pass on every
invocation while the property it claims to protect is false. A rate limiter in memory
would silently permit N times its configured limit, where N is however many lambdas
happen to be warm — a number nobody controls or observes.

D-008 had ingestion publish to an in-process event bus, with listener registration as a
startup precondition. Startup now happens per invocation. Listeners registered at import
time exist only for the invocation that imported them, so the precondition check becomes a
tautology: it passes because the same process that registered the listener is the one
checking, every time.

**Decision**

Rate limiting moves to the database. Limits are enforced by a row per (subject, window)
with an atomic increment, so the enforcement point is the one thing all invocations share.
The check is a single statement, and it is correct under concurrency because the database
serialises it — not because we assume the concurrency is one.

Alert delivery becomes a transactional outbox. The outbox row is written in the same
transaction as the observation that triggers it, and a scheduled invocation delivers
pending rows. Delivery is idempotent and rows are marked delivered only after the send
succeeds.

Both principles from the superseded entries carry forward unchanged: an assumption that
matters is asserted rather than implied, and a path that cannot do its job fails loudly
rather than succeeding quietly. Only the mechanisms change.

**Consequences**

The outbox is a genuine improvement rather than a workaround, and D-010 already said so:
an alert can no longer be lost between "observation committed" and "listener notified",
because those are now one transaction and one durable row. The in-process bus could lose
exactly that window; the outbox cannot.

Rate limiting now costs a database round-trip per checked request, against a database that
scale-to-zeros and bills compute by the hour. That is a real cost against the D-002 budget
and it is not yet measured. It must be measured before the limiter is placed on any path a
visitor can reach repeatedly.

The delivery worker needs a scheduler, and that scheduler is **not decided**. GitHub
Actions cron is the current plan and `docs/SERVICES.md` records the constraint that makes
it doubtful: scheduled workflows are disabled after a period of repository inactivity,
which is precisely the state a finished portfolio project is in. Deciding this needs its
own entry, and Sprint 3 must not begin without it.

**Alternatives rejected**

Keeping in-process state and pinning concurrency to one. Vercel's free plan offers no such
control, so the assumption would be unenforceable — and an unenforceable assumption
asserted at startup is worse than an unasserted one, because it reads as a guarantee.

A queue service for delivery. It is the right tool and it is another external dependency,
another account, and another free-tier limit to inventory. The outbox needs no service that
the project does not already depend on, and the scheduled invocation is required for
ingestion regardless.

---

## D-013 — The sprint go-ahead is delegated to the review agents

- **Date:** 2026-07-29
- **Status:** Accepted
- **Amends:** the hard-stop clause of the phase discipline. D-011's precedent applies —
  a change to what "done" means is a decision, not a process tweak.

**Context**

Every sprint was to end at demo, adversarial review, and an explicit owner go-ahead. In
practice the owner is a bottleneck at every boundary, and Sprint 0 exposed a worse problem:
it *cannot* close on the owner's word alone. Three of its criteria need a secret only the
owner holds, an account only the owner can create, and twenty-four hours of elapsed time.
A contract that requires a go-ahead at a boundary that cannot be reached produces idling,
not control.

**Decision**

The go-ahead is delegated to the agents. `work-breaker` must return PASS to cross a sprint
boundary. A BLOCK means the findings get fixed and the review runs again — it is never
overridden, and "the reviewer was wrong" is a finding to be evidenced, not a verdict to be
waved through. `retro-scribe` writes the boundary retro first, so the crossing is recorded
before it happens rather than reconstructed later.

Owner-blocked criteria do not gate the crossing. They stay unticked, stay listed, and the
work moves on.

**One hard stop remains, and it is not delegated.** The frontend. Work stops at the UI
boundary and hands back, because the owner builds that interface in dialogue rather than
reviewing a finished thing.

**Consequences**

The reviewer becomes load-bearing in a way it was not before: it is now the only thing
standing between a bad sprint and the next one. That is a real risk and it is accepted with
eyes open, on the evidence of its first two runs — it caught a gate check that could not
fail, a vacuous reversibility claim, an unused confusable dependency, and a ticked box
contradicting its own caption. It found more than the sessions it reviewed did.

The mitigation is that everything remains revertable: each iteration is a small gated
commit, and a boundary crossed wrongly is visible in the log rather than lost.

**Not adopted.** Letting a BLOCK be overridden after N attempts, on the model of the Stop
hook's three-strike escape. The Stop hook's escape exists so a session cannot hard-lock a
human out of their own machine. Nothing here is locked: a persistent BLOCK means the work
is not done, and the correct response is to stop and say so.

---

## D-014 — The probe-coverage check binds to argument position, and its failability is gated

**Date.** 2026-07-29. **Supersedes** the coverage mechanism described in D-011's
enforcement note; D-011's rule — that a gate change is itself a decision — stands and is
what requires this entry.

**Context.** Section 4 of `scripts/verify.sh` claimed "every service in SERVICES.md has a
probe." Three implementations of that claim have now existed. The first searched the whole
of `preflight.sh` for the service name, so a comment satisfied it. The second searched only
lines calling the outcome helpers, but still substring-matched the service name against the
concatenated *label text* — so `Vercel` was satisfied by the label `"npx (runs vercel cli)"`
and `Docker` by a postgres failure message. Deleting all four Vercel probes left the gate
green, which was demonstrated before this change rather than argued. The same regex also
excluded every probe written as a `case` arm or an `&&` chain, including the `waive` line,
so the waiver mechanism the gate claimed to honour was invisible to it.

**Decision.**

1. Each row of `docs/SERVICES.md` declares its probes as machine-read `service:name` ids in
   the Probe column. Each id must appear in `scripts/preflight.sh` as the **first argument,
   unquoted, of a `pass`/`fail`/`waive` call**. Comments and quoted spans are removed before
   scanning, so an ordinary label, message, or comment cannot satisfy a row. The binding is
   checked in both directions: an undeclared probe fails too, so a typo reads as a typo.

   The scanner is not a shell parser, and saying so is not a formality. Four shapes did
   satisfy a row wrongly — an indented terminator on a plain `<<` heredoc, a second heredoc
   opened on the same line, `$'...\'...'`, and a quoted span abutting a word, which shell
   concatenates into one token. All four are fixed and pinned as test cases, and
   `check-probes.py` now lists what is known to fool it instead of asserting an invariant
   it cannot hold.
2. One implementation, `scripts/check-probes.py`, is shared by the gate, by `preflight.sh`'s
   own runtime coverage assertion, and by the mutation test. Three copies would drift, and
   drift is how the second version came to be tested against a reimplementation of itself.
3. **Failability is gated, not asserted.** `scripts/test-probe-gate.py` deletes each probe,
   comments it out, renames it, disguises it nine ways, and mutates the manifest three
   ways, requiring the check to notice every time. It runs inside the gate. Two versions
   shipped unfailable because "the fix works" was asserted; this one has to demonstrate it
   on every run.

   Each case is defeated by one identifiable part of the check, so sabotaging **any of the
   parts the cases target** turns the suite red — thirteen sabotages were run to confirm it.
   That is a claim about those parts, not about the check as a whole: a first version of
   this sentence said "any one part", and four sabotages then survived it. Two guards
   genuinely overlap, and the case covering them removes both.
4. `preflight.sh` asserts at the end that every declared probe actually reported, and names
   the count of waived probes in its verdict.

**What this does not do, recorded so it is not rediscovered as a surprise.** The gate's
check is static: it proves an outcome call exists, not that anything reaches it. Probes
moved into an uncalled function, an `if false` branch, a block below `exit 0`, or behind a
`:` builtin still count. `--emitted` closes that and runs inside `preflight.sh` — but
nothing automated runs `preflight.sh`, so reachability is proven only by hand. The gate
deliberately does not run it: the probes are network calls, and a slow flaky gate gets
switched off. A gutted probe body whose outcome call survives is invisible to every mode,
and swapping a probe for a one-line `waive` is green everywhere — hence the waived count.

**Also in this change.** Section 3 now lints and typechecks `scripts/*.py` on the api
toolchain: this code runs inside the gate, and unchecked gate code weakens every check
around it. `src_on_disk()` prunes the two gate helpers **by name** rather than pruning
`scripts/` wholesale, which would have blinded the phase-0 "code before documents" guard
for any project that puts application code there.

**Not adopted.** Gating on `audit/PREFLIGHT.txt` recording a green run. That is offline and
deterministic, but it turns an unrelated local condition — a stopped container — into a red
gate on someone's unrelated commit. The existing rule stands: the gate checks the artifact
exists; whether it is green and fresh is `work-breaker`'s job at the boundary.

## D-015 — Reversibility is established by comparing schemas, not by the round trip exiting 0

- **Date:** 2026-07-29
- **Status:** Accepted
- **Supersedes** the S-002 acceptance criterion "`alembic downgrade base` then `upgrade
  head` succeeds against a real database", and the round trip's appearance in `DEMO.md` as
  evidence.

**Context**

S-002's criterion asked for a command, and the command was run, and it exited 0, and it
was reported as evidence that the migrations are reversible. It establishes nothing. The
only migration in this project is a baseline whose `upgrade()` and `downgrade()` are both
`pass`; an empty migration reverses perfectly, and so does one that drops nothing. This is
the third instance of one shape in this project — a check that cannot fail — after the two
recorded in D-014. The pattern is recognisable in advance now: *would this check notice if
the thing it checks were untrue?* The answer here was no, and could have been read off the
criterion without running anything.

**Decision**

Reversibility is a claim about the database, so it is read from the database.
`api/tests/reversibility.py` snapshots eleven classes of schema object — schemas,
relations, columns, indexes, constraints, types, collations, routines, triggers, policies,
extensions — and `run_round_trip` applies **each migration on its own**, reverses it,
re-applies it, and then exercises the whole chain end to end, snapshotting at every stop. A
migration is reversible when the schema after the reverse is indistinguishable from the
schema before, and re-applying produces what it produced the first time.

Per migration rather than per chain, because a chain-level pass is satisfied by a
`downgrade()` that compensates for damage an earlier migration did, and because a
chain-level failure does not say which migration is at fault. With one migration the two
are indistinguishable; the difference appears exactly when the harness becomes
load-bearing.

Four consequences, each deliberate:

- **The harness reports its own coverage.** `RoundTrip.covered` counts the objects the
  migrations create. Today it is zero, so the round trip proves nothing about *these*
  migrations, and `test_the_round_trip_covers_at_least_one_schema_object` is marked xfail
  with that reason. It reports XPASS the day S-010 adds a table, which is the signal to
  remove the marker rather than a failure to fix.
- **Failure is a verdict, not an exception.** An irreversible migration surfaces three
  ways: schema residue, a `downgrade()` that raises, and a second `upgrade` that collides
  with what the first left behind. A harness that handles only the first reports the other
  two as a crash, which reads as "the test is broken".
- **Its failability is tested, not asserted.** Three sabotage migrations run on every gate
  invocation, one per failure path. Above them, `scripts/sabotage-reversibility.sh` breaks
  the harness seventeen ways and requires each to turn the suite red **for the right
  reason** — by node id, since a mutation that breaks the module import turns everything
  red and would satisfy a check that reads only the exit code — plus one comment-only edit
  that must leave it green.
- **Its off switch is checked.** `reachable()` decides whether any of this runs. A version
  of it that always reported "down" turns the entire integration layer into skips and
  leaves the gate green, which the adversarial review demonstrated with both containers
  healthy. `test_the_skip_decision_matches_reality` opens a socket, sharing no code with
  it, and fails if something is listening while the harness says otherwise. The same review
  found six of the object classes exercised by nothing — `_QUERIES` could be cut to
  relations and columns with byte-identical output — which is why one test now creates an
  object of every class against a real database, and why the expected class list is written
  out rather than derived from `_QUERIES`.

**What this deliberately does not do**

- **No baseline with invented schema.** The obvious way to satisfy the old criterion was to
  write a real baseline migration. The schema is S-010's, in Sprint 1, and CLAUDE.md
  forbids inventing state that an acceptance criterion assumes. A criterion that can only
  be met by building next sprint's work early is a criterion that is wrong.
- **The gate does not provision a database.** These tests skip where none is reachable,
  with a message naming what is then unproven, and `-ra` is in pytest's addopts so the
  message prints. CI provisions no database, so in CI reversibility is skipped rather than
  checked — visible, and not fixed here. `03-QUALITY.md`'s claim that CI runs integration
  tests remains open on the Sprint 0 BLOCK list.
- **`Settings` is not the guard against migrating the wrong database.** It compares two
  strings, so it passes for `localhost` against `127.0.0.1` or a differing query string,
  and it does not run at all when `PREEMPT_DATABASE_URL` is unset — CI, a fresh clone, and
  this project's documented state today. `same_database` compares host, port and database
  name with loopback spellings folded together, and `_skip_unless_database` fails the run
  rather than skipping it. Nothing here drives a database to `base` without that check.
- **The test database is now probed.** `docker:postgres-test` in `SERVICES.md` and
  `preflight.sh` covers the container on 5434. Until this change the one service this
  deliverable depends on had no probe, while `docker:postgres` covered only 5433 — two
  containers from one compose file can still drift, and the audit artifact was making a
  version claim about a service nothing observed.
- **The mutation script is not in the gate.** It edits a tracked file in place. A gate that
  mutates the working tree is one people run only on a clean tree, which is never. It
  refuses to run when any integration test is skipping, because with the containers stopped
  four of its cases report green and it prints holes that do not exist.
- **The xfail is strict.** The day S-010 adds a table, `test_the_round_trip_covers_at_least_
  one_schema_object` starts passing and a strict xfail turns that into a gate failure. That
  is the intent: the marker's reason is no longer true and deleting it is the fix. A
  non-strict marker would report XPASS into a log nobody reads. It also carries
  `raises=AssertionError`, because otherwise pytest converts an exception raised in the
  fixture into XFAIL — and a harness that computed nothing emits the same line this
  project's audit file cites as proof of honest reporting.

**What the harness cannot see**, stated so it is not rediscovered as a surprise: row data,
grants, ownership, RLS policies, triggers, comments, publications, and domain constraints.
A downgrade that destroys a table's contents while restoring its shape reads as reversible.
That gap is why the third sabotage shape seeds *rows* rather than schema — it is the one
case the snapshot is blind to, and without it the re-application step was pinned by nothing
and could be deleted with the suite staying green. The first run of the mutation matrix is
what found that; it is recorded in `audit/REVERSIBILITY.txt` rather than quietly fixed.
