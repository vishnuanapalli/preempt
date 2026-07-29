# Services

Every external thing this project depends on, how the agent reaches it, and the probe that
proves it answers. Written before the code that depends on it, per the `project-preflight`
skill.

`scripts/preflight.sh` implements one probe per row. `audit/PREFLIGHT.txt` is the last
recorded run. A row with no probe is a dependency nobody has verified — that is the defect
class this file exists to eliminate.

| Service | Used for | Account / plan | Agent reaches it via | Probe | Limits that constrain design |
|---|---|---|---|---|---|
| **GitHub** | Source of truth; every push to `main` triggers a deployment | Free, public repo | `git` over HTTPS | `git ls-remote` | Scheduled Actions are disabled after a period of repository inactivity — the Sprint 3 scheduler cannot rely on cron alone |
| **Vercel** | Hosts the FastAPI app | Hobby (free) | `npx vercel@latest` CLI, authenticated as `vishnuanapalli-8269`; Vercel MCP for reads | `vercel whoami`, `rootDirectory`, `vercel env ls` | MCP tools are **read-only** — environment variables must be set via CLI or dashboard. Root Directory (`api`) is a dashboard setting the repo cannot express |
| **Neon** | Production Postgres | Free | Connection string held by the owner; **not reachable from this machine** | **NO DIRECT PROBE.** The closest signal is `PREEMPT_DATABASE_URL` present in Vercel's env list, which proves *configuration*, not connectivity. Real proof arrives when `/ready` reads the database in Sprint 1 | ~400 compute-hours/month, 0.5 GB, five-minute scale-to-zero that cannot be disabled. Only the Apache-2 subset of TimescaleDB — no compression |
| **Docker + timescaledb-oss** | Local dev and test databases (5433 / 5434) | Local | `docker compose` | `server_version`, `pg_available_extensions` | Must use the `-oss` image so a licensed-only feature fails on the laptop rather than in production |
| **uv** | Dependency resolution, and the local `vercel build` reproduction | Local | CLI | `uv --version` against the floor | Vercel refuses to build with uv older than **0.9.25**. Below the floor, local build reproduction is impossible — which is the check that would have caught the 404 in seconds |
| **Uptime monitor** | S-004 criterion 2 | **NOT PROVISIONED** — no account chosen | n/a | none | Must poll `/api/v1/health` only. Polling `/ready` every 15 min would burn ~243 of the 400 monthly compute-hours before a single visitor (D-009) |

## Access the owner must grant

Kept here so the ask is one batch rather than a trickle. Empty is the goal.

1. `PREEMPT_DATABASE_URL` — pooled Neon string, scheme `postgresql+asyncpg://`, query string
   removed. Currently waived; the waiver lifts when S-004 closes or the first query ships.
2. An uptime-monitor account, once one is chosen.
3. `uv self update` — the installed 0.9.18 is below Vercel's floor, so the local build
   reproduction that ledger R3 requires cannot run.
