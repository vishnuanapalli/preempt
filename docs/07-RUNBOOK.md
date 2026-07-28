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

<!-- Production data is synthetic by design, so the seed script IS the backup strategy.
     This is the recovery path for a bad migration, and the only one. -->

```bash
# the literal command
```

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
