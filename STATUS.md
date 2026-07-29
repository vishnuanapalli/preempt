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
| S-001 gate is real and runs in CI | **Not done.** The gate runs in CI structurally, but no artifact anywhere records the red run. `03-QUALITY.md` DoD 2 requires that output on record and `docs/DEMO.md` explicitly refuses to hold it — a criterion and its deliverable contradicting each other |
| S-002 database provisioned, migrations reversible | **Not done.** The reversibility round-trip was run against a baseline whose `upgrade()` and `downgrade()` are both `pass`, so it proves nothing. The Neon-branch test database was also replaced by a local one with no ADR |
| S-003 health endpoint reporting freshness | **Partial.** `/health` and `/ready` split per D-009; `/ready` still returns nulls because no tables exist yet |
| S-004 live on the public internet | **Partial.** Serving over HTTPS since `43673c8`; one of six acceptance criteria met — see below |
| S-005 seed script | **Not started** |

## The Vercel problem — resolved 2026-07-28 in `43673c8`

The app now serves. Kept here because the diagnosis is the useful part.

Live values are **not pasted here** — they go stale in minutes and this file then reads as
evidence for something that is no longer true. `audit/PREFLIGHT.txt` holds the last
recorded run; `bash scripts/preflight.sh` refreshes it.

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
without a deploy cycle. Reach for that first next time.

```sh
npx vercel@latest pull --yes --environment production   # writes .vercel/project.json
npx vercel@latest build --prod                          # inspect .vercel/output/
```

The CLI is not installed globally — `npx vercel@latest` is the invocation, and `--cwd`
avoids needing to `cd`. It is already authenticated as `vishnuanapalli-8269`, so the
pull works; an earlier session concluded otherwise after mistaking an `npx` package
download for a login prompt. Note that Vercel requires a reasonably new `uv` and refuses
to build with an older one, which is a local-only obstacle — the cloud builder has its
own.

**Still a dashboard setting:** Root Directory is `api`, confirmed by reading
`.vercel/project.json` after a pull rather than by inference. The repo cannot express it,
so it is the one part of this that can be silently lost. Project settings carry no
framework preset — `api/vercel.json` is what selects the Python builder.

## Environment

- **Local:** `docker compose up -d --wait` gives Postgres 18.1 + timescaledb 2.24.0 on
  port 5433, and an ephemeral test database on 5434. Matches Neon's 18.4 / 2.24.0.
- **Neon:** project exists, reachable, `timescaledb` and `pg_partman` both available.
  Used by production only — dev and tests run locally so the 400 CU-hour monthly budget
  is not spent on test runs.
- **`api/.env`** holds local connection strings. Gitignored. The Neon connection string is
  deliberately not stored in any file; it goes into Vercel's environment variables.

## Process system, added 2026-07-28

`docs/SERVICES.md` + `scripts/preflight.sh` + `docs/10-FRICTION.md`, enforced by section 4
of the gate. Run `bash scripts/preflight.sh | tee audit/PREFLIGHT.txt` when a service is
added or access changes. Do not restate its result here — this paragraph previously
asserted a `uv` failure that `audit/PREFLIGHT.txt` had already recorded as cleared, which
is exactly the rot the "no pasted live values" rule above exists to prevent, in the file
that states the rule. Read the artifact. The Neon row is waived in writing until Sprint 1.

Full rationale and the cross-project rules: `~/.claude/PROCESS-LEDGER.md`.

## Next actions, in order

1. **Finish the environment variables** (S-004). `PREEMPT_ENVIRONMENT=production` is set
   and live. `PREEMPT_DATABASE_URL` is still unset and waived in `SERVICES.md` — it needs
   the **pooled** Neon endpoint, scheme `postgresql+asyncpg://`, query string removed;
   pooling is mandatory under D-010, not optional. Nothing reads the database yet, so the
   app serves without it — which is exactly how this stays forgotten. Check the current
   state with `bash scripts/preflight.sh`, not with a value pasted into a document.
2. **External uptime monitor** on `/api/v1/health` every 15 minutes (S-004). Poll only
   `/health` — `/ready` costs compute budget, per D-009.
3. **Measure and record** cold-start duration after an hour idle, and CU-hours consumed
   in the first 24 hours. `01-DESIGN.md` asserts these; if reality disagrees, that is an
   ADR, not a silent edit.
4. **Seed script** (S-005), then close Sprint 0 with a demo and an adversarial review.
5. Sprint 1: schema, simulator, Azure provider.

## Open threads

- **The test suite is bundled into the production function**, and neither documented
  mechanism excludes it. Tried and verified not to work, so nobody repeats them:
  `api/.vercelignore` with `tests/`, and `functions."app/main.py".excludeFiles` in
  `vercel.json`. Both build fine and change nothing — `filePathMap` still lists all three
  test files. The documented `excludeFiles` example targets the legacy `api/**/*.py`
  layout, not the framework builder that emits a single `fastapi.func`. Left alone
  deliberately: three small files inside a private bundle, not served publicly, and not
  worth more cycles. Revisit only if the 500 MB bundle limit ever comes into play.
- **S-004's acceptance criteria still say "Deployed to Koyeb."** D-010 chose Vercel and
  the backlog was never updated. The remaining five criteria are still the right ones;
  only the platform name is stale. Fix the wording when S-004 is closed, so the checklist
  is not signed off against a platform this no longer uses.
- ~~D-010 obsoleted parts of D-007 and D-008.~~ **Resolved by D-012**, which replaces both
  mechanisms — database-backed rate limiting and a transactional outbox — and keeps their
  principles. Still unbuilt, but no longer a trap: read D-012, not the original wording of
  D-007 and D-008. Two things D-012 leaves open on purpose: the per-request database cost
  of rate limiting is unmeasured against the D-002 budget, and the scheduler is undecided.
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
- **An empty commit no longer redeploys.** `ignoreCommand` skips any push that changes
  nothing under `api/`, which is the point — but it also breaks the trick used on
  `ad5913e` to pick up a new environment variable. To redeploy without a code change:
  `npx vercel@latest redeploy <deployment-url> --scope vishnus-projects-2166f0a0`.
- **Do not build the frontend solo.** When the work reaches `06-UI-SPEC.md` and the UI,
  stop and hand back. The owner has said explicitly that the frontend is a back-and-forth
  process, not something to be produced in one pass and reviewed after. Backend, data, and
  infrastructure continue as normal.
