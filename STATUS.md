# Where this project is

Working state for whoever picks this up next, including me in a fresh session. The
documents in `docs/` are the source of truth for *what* and *why*; this file is only
*where we stopped*. Delete anything here that has become false rather than letting it rot.

Last updated: 2026-07-28.

## Current position

**Phase 4 complete** (`docs/.phase` = 4). All planning documents are written. Sprint 0 is
in progress.

| Story | State |
|-------|-------|
| S-001 gate is real and runs in CI | **Done.** Verified by injecting a defect and watching CI go red |
| S-002 database provisioned, migrations reversible | **Done.** upgrade → downgrade → upgrade against real Postgres |
| S-003 health endpoint reporting freshness | **Partial.** `/health` and `/ready` split per D-009; `/ready` still returns nulls because no tables exist yet |
| S-004 live on the public internet | **Partial.** Serving over HTTPS since `43673c8`; one of six acceptance criteria met — see below |
| S-005 seed script | **Not started** |

## The Vercel problem — resolved 2026-07-28 in `43673c8`

The app now serves. Kept here because the diagnosis is the useful part.

```
$ curl -si https://preempt-tau.vercel.app/api/v1/health | head -1
HTTP/2 200
{"status":"ok","environment":"local","ingest_interval_seconds":1800}
```

- Project: `preempt`, team `vishnus-projects-2166f0a0` (`prj_Brjcgy18oF1blb2WsULftvbE6JZK`)
- `/api/v1/health` and `/api/v1/ready` return 200; `/docs` renders; an unknown route
  returns FastAPI's `{"detail":"Not Found"}` rather than a platform 404, which is what
  distinguishes "the app is serving" from "the CDN answered."

**Root cause.** No function was ever built. With Root Directory `api` and no framework
preset, Vercel classified the project as a *static site*: it copied every `.py` file into
`.vercel/output/static` and emitted a single catch-all 404 route. `[tool.vercel]
entrypoint` was never consulted, because no Python builder ran to read it. The fix is
`api/vercel.json` declaring `"framework": "fastapi"`, which produces output identical to
setting the preset in project settings but lives in the repo.

**Two things the earlier notes got wrong**, both worth remembering:

- "Dependencies never install" was the leading hypothesis and was false. The build log
  showed `uv` resolving `uv.lock` successfully all along.
- `{"python": 2}` was recorded as *unchanged across all three attempts*. It was not: the
  third deployment reported no `lambdaRuntimeStats` at all. Reading it as unchanged
  merged two different failures into one and pointed the investigation at configuration
  syntax instead of at builder selection.

**What actually found it:** `vercel build` run locally against a copy of `api/`. It uses
the same detection as the cloud, so the empty output directory was visible in seconds
without a deploy cycle. Reach for that first next time. It needs a hand-written
`.vercel/project.json` (`projectId`, `orgId`, `settings`) to skip the authenticated pull,
and a `uv` at least as new as the one Vercel requires.

**Still a dashboard setting:** Root Directory must remain `api`. The repo cannot express
it, so it is the one part of this that can be silently lost.

## Environment

- **Local:** `docker compose up -d --wait` gives Postgres 18.1 + timescaledb 2.24.0 on
  port 5433, and an ephemeral test database on 5434. Matches Neon's 18.4 / 2.24.0.
- **Neon:** project exists, reachable, `timescaledb` and `pg_partman` both available.
  Used by production only — dev and tests run locally so the 400 CU-hour monthly budget
  is not spent on test runs.
- **`api/.env`** holds local connection strings. Gitignored. The Neon connection string is
  deliberately not stored in any file; it goes into Vercel's environment variables.

## Next actions, in order

1. **Set the environment variables** (S-004). Production currently answers
   `"environment":"local"`, because none are set — that is the live proof they are
   missing. Needs `PREEMPT_ENVIRONMENT=production` and `PREEMPT_DATABASE_URL` pointed at
   the **pooled** Neon endpoint; pooling is mandatory under D-010, not optional. Nothing
   reads the database yet, so the app serves without them — which is exactly how this
   stays forgotten.
2. **External uptime monitor** on `/api/v1/health` every 15 minutes (S-004). Poll only
   `/health` — `/ready` costs compute budget, per D-009.
3. **Measure and record** cold-start duration after an hour idle, and CU-hours consumed
   in the first 24 hours. `01-DESIGN.md` asserts these; if reality disagrees, that is an
   ADR, not a silent edit.
4. **Seed script** (S-005), then close Sprint 0 with a demo and an adversarial review.
5. Sprint 1: schema, simulator, Azure provider.

## Open threads

- **S-004's acceptance criteria still say "Deployed to Koyeb."** D-010 chose Vercel and
  the backlog was never updated. The remaining five criteria are still the right ones;
  only the platform name is stale. Fix the wording when S-004 is closed, so the checklist
  is not signed off against a platform this no longer uses.
- **D-010 obsoleted parts of D-007 and D-008.** Rate limiting must move to the database
  and the delivery worker becomes a scheduled invocation. Neither is built yet — Sprint 3
  must not be started from the original wording of those two entries.
- **The scheduler is undecided in detail.** GitHub Actions cron is the plan, but scheduled
  workflows are disabled after a period of repository inactivity. Confirm before relying
  on it.
- **The pool-clustering statistic in D-004 is unverified.** The paper exists; that specific
  number was not confirmed from its abstract. Do not cite it in the case study without
  reading the full paper.
- **`docs/09-LEARNING.md` is still empty** and becomes due at phase 5.

## Conventions that are easy to get wrong

- Never `sleep` in a shell command on this machine — a hook blocks it. Use `command sleep`
  or, better, do not poll at all.
- `docs/.phase` gates which documents are required. Bump it only when a phase is genuinely
  complete; the gate is what makes that claim checkable.
- The decision log is append-only. Supersede, never edit.
