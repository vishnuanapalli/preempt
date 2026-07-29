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
| S-004 live on the public internet | **Not started.** Blocked on the Vercel deploy |
| S-005 seed script | **Not started** |

## Environment

- **Local:** `docker compose up -d --wait` gives Postgres 18.1 + timescaledb 2.24.0 on
  port 5433, and an ephemeral test database on 5434. Matches Neon's 18.4 / 2.24.0.
- **Neon:** project exists, reachable, `timescaledb` and `pg_partman` both available.
  Used by production only — dev and tests run locally so the 400 CU-hour monthly budget
  is not spent on test runs.
- **`api/.env`** holds local connection strings. Gitignored. The Neon connection string is
  deliberately not stored in any file; it goes into Vercel's environment variables.

## Next actions, in order

1. **Deploy to Vercel** (S-004). Root directory `api/`, Python runtime. Set
   `PREEMPT_DATABASE_URL` to the **pooled** Neon endpoint in Vercel's environment
   variables — pooling is mandatory under D-010, not optional.
2. **Measure and record** cold-start duration after an hour idle, and CU-hours consumed
   in the first 24 hours. `01-DESIGN.md` asserts these; if reality disagrees, that is an
   ADR, not a silent edit.
3. **Seed script** (S-005), then close Sprint 0 with a demo and an adversarial review.
4. Sprint 1: schema, simulator, Azure provider.

## Open threads

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
