# Learning log

Two things live here: what was learned building this, and what went wrong.

The second matters more. Entries are written the day it happened, because a
reconstruction three months later is a story, not a record.

## Post-incident notes

### 2026-07-28 — A green status meant nothing, twice in one day

**What happened**

Twice, a system reported success while doing nothing of the kind.

CI passed on a commit where the workflow never ran: `astral-sh/setup-uv@v9` does not
resolve, because that repository publishes `v9.0.0` with no moving `v9` major alias. The
job failed at action resolution, before any step executed.

Vercel reported a deployment `READY` and served `404` on every route. It had auto-detected
two Python functions and built those; the FastAPI application at `api/app/main.py` was
never deployed. Setting the root directory and declaring an explicit entrypoint did not
fix it — the next deployment still reported `{"python": 2}`.

**Root cause**

Both are the same shape: a status indicator reporting on a *proxy* for the thing that
matters. "The workflow file was accepted" is not "the tests ran." "A deployment finished"
is not "the application serves."

**What now catches it**

Never accept a status badge as evidence. The check is the actual thing: `curl` the endpoint
and read the body, or read the gate's own output from inside the run. Both incidents were
caught in seconds that way, and would have shipped otherwise.

This is never-ship item 1 — a check that reports success without verifying what it claims
to check — occurring in tooling rather than in our own code.

### 2026-07-28 — Recalled facts were wrong three times

**What happened**

Three assumptions carried from memory were wrong, and each failed only on execution:

- `actions/checkout@v4` and `setup-uv@v5` were several major versions stale (v7, v9).
- `setup-uv` publishes no moving major alias, though `actions/checkout` does. Reading the
  latest *release tag* and assuming a matching alias exists is not the same as checking
  that the ref resolves.
- `grep -P` does not exist on macOS. A credential rule using a negative lookahead matched
  nothing locally while working in CI — a gate silently disagreeing with itself across
  environments, which is worse than no gate.

**What now catches it**

Version, tag, and API-surface claims are verified by execution before use. The database
choice was made that way and it paid: querying Neon directly showed PostgreSQL 18.4 with
`timescaledb 2.24.0`, which is what let local Docker be pinned to match exactly.

### 2026-07-28 — A test asserted the developer's machine, not the code

**What happened**

`test_no_credential_defaults` asserted `Settings().api_key == ""`. It passed until a local
`.env` existed, then failed — pydantic-settings loads `.env` by default, so the test was
reading whatever happened to be on that machine.

**Root cause**

The test named a property of the *code* but constructed the object the way the
*application* does, environment and all.

**What now catches it**

`Settings(_env_file=None)`. Generally: a test of declared defaults must construct the
object in isolation from the environment, or it is testing the machine it runs on.

## Concepts learned

### Free-tier limits are architecture, not a deployment detail

Neon allows ~400 compute-hours a month against a ~730-hour month, and cannot disable
five-minute scale-to-zero. Any query wakes the database for a five-minute minimum.

Two design decisions fall straight out of that arithmetic. The ingest cadence is thirty
minutes, because a five-minute tick keeps the database permanently awake and exhausts the
month around day sixteen. And `/health` cannot touch the database, because an uptime
monitor polling it every fifteen minutes would hold the compute awake a third of the
month — 243 hours against a 400-hour budget, before a single visitor.

**What surprised me:** the second was a contradiction between two sections of a design
document I had just written. One specified fifteen-minute monitoring; another estimated
compute cost counting only the scheduler. Neither was wrong alone. The lesson generalises:
a budget derived from one component's behaviour must be recomputed as a union across
everything that touches the resource.

### Environment parity is about capability, not just version number

Neon's free tier offers only the Apache-2 subset of TimescaleDB, which is why compression
is unavailable there. Local Docker therefore uses the `-oss` image rather than the full
one, so a licensed-only feature fails on a laptop instead of in production. Matching the
version number is not enough when two environments differ in what they are *allowed* to do.

## Things I would do differently

- Deploy the walking skeleton before writing any entrypoint configuration. The deployment
  surface had a problem no amount of local verification would have found, and finding it
  earlier would have cost less.
- Establish that a status source reports on the thing itself before trusting it even once.
