# Preempt — product requirements

Phase 0. Written before any design work, so Phase 1 has something concrete to design
against.

## The problem

Every major cloud sells leftover computing capacity at a steep discount — often 70 to 90
percent below the normal price. The catch is that the provider can take the machine back
with about two minutes' notice when a full-price customer wants it. AWS calls this a spot
instance, Google calls it preemptible, Azure calls it a spot VM. The name differs; the
deal is the same.

For a company where cloud is a top-three expense, that discount is real money. Most teams
still do not use it, for two reasons.

The first is that nobody can tell them which machines are actually safe to use. The risk
is not evenly spread. A particular machine type in a particular data centre may be
reclaimed constantly, while a near-identical one next door stays up for weeks. That
information is scattered, inconsistent between providers, and in some cases not published
at all.

The second is that comparing the three clouds is genuinely difficult, and not because
anyone is being obtuse. Each one prices differently. AWS quotes a single price per
instance. Google quotes separate prices per CPU and per gigabyte of memory, which have to
be assembled into a machine price before a comparison is even possible. Azure publishes
its own schedule again. So the plain question — "for a machine with 8 CPUs and 32
gigabytes of memory, who is cheapest, and will it survive the night?" — has no simple
answer today.

Preempt answers that question.

## Who it is for

**Priya, platform engineer at a forty-person startup.** Cloud is her company's second
largest expense after payroll. Her CTO has asked for a thirty percent reduction. She knows
the discount tier exists. She has no way to tell which machines are safe enough to move
her workloads onto, so she has not moved any.

**Marcus, data engineer.** He runs batch jobs overnight. Interruption is genuinely fine —
his jobs restart. What he needs is to pick the machine least likely to vanish halfway
through, and to be told when the pool he settled on starts looking risky, before he
schedules tomorrow's run against it.

Both need the same two things: a fair comparison across providers, and an honest signal
about risk.

## What this project proves

- Designing a system across three external providers whose data models genuinely disagree.
- Time-series data modelling: schema, keys, retention, and query patterns at millions of rows.
- Normalising incompatible pricing schemes into one comparable unit — the load-bearing
  piece of the whole system.
- Event-driven alerting with real delivery guarantees, not a fire-and-forget webhook.
- A prediction that reports its own accuracy, evaluated on data it never trained on.
- Being explicit in the product itself about what the data is and is not.

## Success criteria

Each is either true or false on inspection.

1. Given a CPU and memory requirement, the API returns the cheapest equivalent machine on
   each provider, and states the basis on which they were made comparable.
2. Any tracked machine's price history is queryable over a ninety-day window.
3. A user can register a rule and receive a signed webhook when it fires. Delivery survives
   the receiver being down: it retries, it does not duplicate effects, and it does not
   silently drop.
4. Interruption risk is reported per pool — a machine type in a specific location — with a
   confidence interval and the sample size behind it.
5. Every response carrying a prediction also carries a machine-readable field stating that
   the underlying data is simulated. This is structurally required, not a page footer.
6. The prediction publishes a reliability diagram and a Brier score, computed on a holdout
   set the calibration step never touched.
7. The whole system runs on free-tier hosting at zero monthly cost.
8. One command — `./scripts/verify.sh` — decides whether the project is green, and CI runs
   the same command.

## Non-functional requirements

| Requirement | Target | Why |
|-------------|--------|-----|
| Hosting cost | $0/month | Free tier is a design constraint, not an afterthought |
| Read latency | p95 under 500ms for comparison and history queries | It has to feel usable in a live demo |
| Data honesty | Simulated data labelled in every response that depends on it | The credibility of everything else rests on this |
| Retention | 90 days of price history | Enough to show a trend, bounded enough for a free-tier database |
| Recovery | Back up within ten minutes using only the runbook | Free tiers suspend; the demo has to survive that |

## Explicitly out of scope

- **Live provider data.** AWS and Google both require credentials and, in practice, a
  billing relationship. A market simulator stands in, and every surface that shows its
  output says so. This is the single biggest limitation, and it is stated first and in
  public rather than discovered by a reviewer.
- **Buying or provisioning anything.** Preempt informs a decision. It does not touch a
  cloud account, and it never will — that is a different product with a different risk
  profile.
- **General cost optimisation.** No rightsizing, no reserved-instance advice, no idle
  detection. The scope is price and interruption risk for the discount tier.
- **User accounts.** API keys authenticate writes. There is no sign-up, no billing, no
  multi-tenancy.
- **A mobile application.** The web interface is responsive; that is the whole story.

## Open questions

Each must be resolved before Phase 1 is finished, and each becomes an entry in the
decision log.

1. **Should real Azure data be used?** Azure's retail price list is public and needs no
   credentials, so genuinely real prices are available for one of the three providers.
   That is more credible than a fully simulated system, but a mixed system is harder to
   explain honestly and harder to compare fairly. Worth deciding deliberately rather than
   defaulting into.
2. **What is the unit of risk?** Prior work in this area points to the pool — a machine
   type in a specific zone — rather than the individual machine, because reclamations
   cluster tightly within a pool. This needs confirming before the schema is fixed,
   because it determines the primary key.
3. **Where does it run?** The free-tier provider decides the database, the scheduler, and
   what "always on" actually means in practice. Phase 1, and it needs a runbook entry.
4. **How much prior work carries over?** Substantial earlier work exists in this domain.
   Phase 1 decides what is ported and what is rebuilt, and the decision log records why.
   This project only means something if the judgment in it is mine.

## What this is not claiming

The prediction is trained on simulated data. That makes it an honest demonstration of a
method — feature design, calibration, held-out evaluation — and not evidence that it
would predict real reclamations. Saying so plainly, in the product and in an interview, is
the point. A calibration curve that looks perfect because the model was graded on its own
training data is the specific failure this project exists to avoid.
