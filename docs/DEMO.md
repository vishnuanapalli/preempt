# Demo

One section per sprint. Each is a path someone can run to see what the sprint actually
produced, ending in a state they can judge.

**No command output is pasted here.** It goes stale within minutes of the next deployment,
and a document that reads as evidence for something no longer true is worse than one that
says nothing. Run the commands; `audit/PREFLIGHT.txt` holds the last recorded run.

---

## Sprint 0 — the walking skeleton

**What it claims:** the smallest thing that can be deployed to real infrastructure and
answer a request, with a gate that can actually fail and dependencies that have been
proven rather than assumed.

**What it does not claim:** anything about prices, providers, or data. Nothing reads the
database yet. `/ready` returns nulls by design — Sprint 1 gives it something to report.

### 1. The gate can fail

```sh
./scripts/verify.sh                 # four sections, expect VERIFY: PASS
```

It is only worth trusting because it has been seen to go red. Break something and watch:

```sh
mv docs/10-FRICTION.md /tmp/ && ./scripts/verify.sh ; mv /tmp/10-FRICTION.md docs/
```

### 2. Every dependency answers

```sh
bash scripts/preflight.sh           # expect PREFLIGHT: PASS
```

Six services, each printing the value observed rather than the word "ok". One row —
Neon — is exempt in writing (`NO DIRECT PROBE`), because it is not reachable from this
machine and pretending otherwise is how a probe comes to measure nothing.

### 3. The database is real and reversible

```sh
docker compose up -d --wait
cd api && uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
```

Local Postgres matches Neon on capability, not just version: the `-oss` image means a
licensed-only feature fails on a laptop instead of in production.

### 4. It is live, and the app is what answers

```sh
curl -s "https://preempt-tau.vercel.app/api/v1/health?cb=$(date +%s)"
curl -s "https://preempt-tau.vercel.app/nope"
```

The second matters more than the first. A FastAPI `{"detail":"Not Found"}` proves the
application is routing; a platform 404 would mean the CDN answered and the app was never
reached. That distinction is the entire Sprint 0 bug — the deployment reported `READY`
and served 404s for three deploy cycles.

### 5. The build reproduces locally

Run these from the **repository root**, not from `api/` — the link lives at the root and
Vercel applies the `api` Root Directory itself. Running them inside `api/` fails with
"No project settings found locally", which reads like a build problem and is not one.

```sh
npx vercel@latest pull --yes --environment production
npx vercel@latest build --prod && ls .vercel/output/functions/
```

Expect one `fastapi.func`. An empty output directory is the failure that cost three deploy
cycles, and it is visible here in seconds. This needs `uv` at or above the floor in
`docs/SERVICES.md`; below it the build refuses to start, which is why that floor is a
probe and not a footnote.

**Judge it on:** whether the gate caught the defect you injected, whether preflight named
a real dependency rather than a plausible one, and whether step 4 distinguished the app
from the platform. Those three are the sprint.
