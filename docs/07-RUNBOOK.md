<!-- TEMPLATE:UNFILLED — delete this line once this document is genuinely filled in. -->
# Runbook

Phase 7. What to do when the live demo is broken and you have twenty minutes before an
interview. Written while things work, because it is useless written afterwards.

Everything here is a literal command that can be pasted. No "redeploy the service" —
the actual command, with the actual service name.

## Where it runs

| Piece | Provider | Console URL | Free-tier limit that bites |
|-------|----------|-------------|----------------------------|
| API | | | |
| Database | | | |

## Deploy

```bash
# the literal command
```

**How to confirm it worked**

```bash
curl -fsS https://<host>/api/v1/health
```

## Roll back

```bash
# the literal command
```

<!-- If rollback is "redeploy the previous commit," write that command out. If there is
     no rollback path, say so here plainly — an honest gap you can name in an interview
     beats a procedure that does not exist. -->

## Rebuild the demo dataset

The seed script is the backup strategy. There is no other recovery path, and there does not
need to be: nothing here is data a user gave us.

```bash
cd api && uv run alembic upgrade head        # schema first
cd api && uv run python ../scripts/seed.py   # then the catalog
```

Safe to run twice. Idempotent by construction — `ON CONFLICT DO NOTHING` on the natural key,
so there is no window between a check and an insert for a second run to slip through.

**Seed the catalog before ingestion, not after.** The writer refuses to invent `vcpu` and
`memory_mb` for an instance type it has not seen (D-019), so a tick against an unseeded catalog
stores nothing and reports every observation as `unknown_instance_type`. That count is the
symptom to look for: a real run against a seeded catalog reports most observations unknown only
because the curated set is a deliberate subset — measured live, 3,194 fetched, 24 stored, 3,170
unknown, which is the intended shape and not a fault.

What the seed does **not** restore: `price_metric` history. Those rows come from ingestion
ticks and are gone for good. Losing them costs the demo its history until enough ticks have run
again, which is the honest limit of this recovery path rather than a gap to paper over.

## Environment variables

<!-- Every variable the app needs, where the real value lives, and what breaks without
     it. Never the values themselves. Mirror this list in .env.example. -->

| Variable | Purpose | Breaks if missing |
|----------|---------|-------------------|
| | | |

## Free-tier keep-alive

<!-- Free tiers idle-suspend services and pause databases after inactivity. "Always on"
     is a claim that needs a mechanism behind it. Record what suspends, after how long,
     and what prevents or detects it. -->

| What suspends | After | Prevented / detected by |
|---------------|-------|-------------------------|
| | | |

## Migrations

<!-- With one production database and no staging, a bad migration is the most likely way
     to destroy the live demo. Write the policy down before you need it. -->

- Forward-only. No destructive migration without a seed-rebuild plan written first.
- Migrations run from CI, never from a laptop.
- Recovery from a bad migration: rebuild from the seed script above.

## When it is down

1. Is it suspended, or is it broken? Check the provider console first.
2. `curl` the health endpoint — what does it actually say?
3. Check logs: `<command>`
4. If unclear after five minutes, redeploy the last known-good commit rather than debug live.
