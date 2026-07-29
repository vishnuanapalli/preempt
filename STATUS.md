# Where this project is

Working state for whoever picks this up next, including me in a fresh session. The
documents in `docs/` are the source of truth for *what* and *why*; this file is only
*where we stopped*. Delete anything here that has become false rather than letting it rot.

Last updated: 2026-07-29. BLOCK item 1 closed (D-014, work-breaker PASS). Item 2 built and
fixed against a BLOCK review (D-015); re-review pending, and its box stays unticked until
that returns PASS. Items 11 and 12 were opened by the reviews of item 1; item 13 by item 2's.

## Running this autonomously

The loop below is the intended way to work this project. It is self-contained: every
iteration reads state from disk, so it survives a `/clear` and does not depend on any
conversation. Start it in a **fresh session**.

> /loop Read ~/Desktop/preempt/STATUS.md first and verify it against `git log` and
> `./scripts/verify.sh` before trusting a word of it. Then do ONE bounded piece of work:
> the top unresolved item on the Sprint 0 BLOCK list below, or if that list is empty, the
> next story in docs/05-BACKLOG.md. Run `./scripts/verify.sh` and paste its output —
> nothing is done until it passes. After any substantive deliverable, run the work-breaker
> agent on model opus and fix every BLOCK finding before moving on; never override a BLOCK.
> At each sprint or phase boundary, run the retro-scribe agent and let it write
> docs/10-FRICTION.md before crossing. Commit and push each iteration, and update STATUS.md
> with where you stopped and what is now blocked. If an item is blocked on the owner
> (database URL, uptime-monitor account, the 24-hour CU-hours window), record it, leave its
> criterion unticked, and move to the next item rather than waiting. HARD STOP: write no
> frontend, UI, or 06-UI-SPEC implementation — when the work reaches that boundary, stop
> the loop and report. Never sleep and never poll.

Authority for this is D-013. The frontend stop is not delegated and not negotiable.

## Sprint 0 BLOCK list

From the adversarial review of 2026-07-29 (15 findings, verdict BLOCK). This is the loop's
work queue: take the top unresolved item, fix it, verify, commit, tick it here. Ordered by
severity. Sprint 0 cannot close while any of 1–8 is open.

- [x] **1. Gate §4's probe check cannot detect a deleted probe.** Fixed 2026-07-29, D-014.
      Re-ticked with the box scoped to the defect it names, per the round-five review: the
      delete-a-probe case has been red since `147cc77` and re-verified at every commit since.
      The rolling verdict lives in the Review state line and in item 12, not in this box —
      as written it was tracking two different things and would untick every time a review
      found a shape narrower than the last one.
      The defect was reproduced first (`6|` — six rows, zero missing, with every Vercel
      probe deleted) rather than taken on trust. Each row of `SERVICES.md` now declares
      machine-read `service:name` ids; each must appear as the first **unquoted argument**
      of a `pass`/`fail`/`waive` call, with comments and quoted spans stripped before
      scanning. One shared implementation (`scripts/check-probes.py`) serves the gate,
      preflight's runtime coverage assertion, and the mutation test.
      `scripts/test-probe-gate.py` runs in the gate and proves the check can fail —
      thirty-six cases in both directions, mutating **both** of the check's inputs, since the guards against a
      vacuous check live on the manifest side and a first version that mutated only
      `preflight.sh` left them untested. Seventeen sabotages of the check were run to confirm
      each targeted part turns the suite red. Ported to the template, still green on a
      fresh run.
      **Residual gap, stated not hidden:** `--static` proves a call exists, not that it is
      reached; probes hidden in an uncalled function, an `if false` branch, below `exit 0`,
      or behind `:` still count. `--emitted` proves reachability and preflight asserts it —
      but nothing automated runs preflight. See D-014 and the `check-probes.py` docstring.
      **Review state: `work-breaker` PASS on `030d83a`; two MAJORs from that round fixed
      since.** Five rounds, every finding correct, each a different instance of one mistake:
      claiming coverage that had not been demonstrated. (1) a mutation case that could not
      fail; (2) the suite testing only one of the check's two inputs; (3) PASS; (4) keywords
      offered as a bare alternative, so `echo then pass a:b` counted — falsifying, in the same
      commit, the comment claiming that hole was closed; (5) `{`/`}` unconditional in the
      separator class, same shape with braces, **and** the structural gap that every case
      asserted the check goes *red*, so no false-FAIL regression was catchable at all.
      That last one had hidden an unpinned mechanism for three rounds. Fixed: `{` must earn
      command position like any other reserved word, and the suite now has inverted
      must-stay-green cases. The same round also found the noise-as-finding shape surviving
      in `--emitted`: stray text in the coverage file was reported as a probe that ran, so a
      fabricated failure, fixed once in the test harness and missed one file over. Both sides
      now filter. 36 cases, both directions; sabotages caught include reverting each of the
      last three rounds' regressions.

- [ ] **2. S-002's reversibility is vacuous.** Built 2026-07-29, D-015. **Unticked, and the
      only thing outstanding is the re-review.** Round one returned BLOCK — 5 BLOCK, 5 MAJOR,
      8 MINOR, every finding correct — and all of them are fixed at `2bf1c96`. The re-review
      has been attempted **four** times and died each time to `API Error: 529 Overloaded`,
      which is server-side and unrelated to this repo. Nothing in the work is known to be
      wrong; nothing has cleared it either. **Resume by running `work-breaker` on model opus
      against HEAD** — the brief is in the loop's history, and the fixes it needs to check are
      listed below. Do not tick this box on the strength of a green gate: the gate was green
      for the version that then collected ten findings.
      While the reviewer was unavailable, the one gap it had flagged as unreachable was
      closed with evidence instead of reasoning: chain stepping. With a single migration
      every branch that visits the next revision, stops at a failure, names the culprit or
      reports the rest unstepped was dead code under test — removing the `break` left the
      suite green. Two tests now build a real three-migration chain in a temporary version
      location, and mutation cases 6–8 cover it.
      Built as scoped: a reversibility harness rather than a baseline with invented schema.
      `api/tests/reversibility.py` snapshots eleven classes of schema object and steps each
      migration — apply, reverse, re-apply — before exercising the whole chain;
      `api/tests/test_reversibility.py` runs it on every gate invocation with three
      deliberately irreversible migrations, one per failure path;
      `scripts/sabotage-reversibility.sh` breaks the harness twenty-two ways by hand and
      requires each to go red *by node id*. Evidence: `audit/REVERSIBILITY.txt`.
      **Coverage is zero and the harness says so.** The baseline creates nothing, so the
      round trip has nothing to reverse. The strict xfail on
      `test_the_round_trip_covers_at_least_one_schema_object` fails the day S-010 lands,
      which is the day to delete it — that is now a criterion on S-010.
      **The first version was believed done twice.** The mutation matrix's first run found
      three unpinned mechanisms; the review that followed found five more, including a
      one-line off switch in `reachable()` that removed every database-backed test while
      the gate reported PASS. Both rounds are in `audit/REVERSIBILITY.txt` §4 and
      `docs/10-FRICTION.md`. Also fixed along the way: the test database on 5434 had no
      preflight probe (`docker:postgres-test` now), and `S-006` — a story that has never
      existed — was cited in six files as the trigger for the harness becoming load-bearing.
      The schema story is **S-010**.
- [ ] **3. S-001 has no evidence artifact, and its deliverable refuses to hold one.**
      `03-QUALITY.md` DoD 2 requires verify.sh output on record; `docs/DEMO.md` says "no
      command output is pasted here". Resolve the contradiction, then record the red-CI run.
- [ ] **4. `04-PLAN.md:86` and `:98` still order the D-007/D-008 mechanisms built** —
      the single-instance assertion and startup listener precondition D-012 calls actively
      misleading. Also `05-BACKLOG.md:165`. Point them at D-012.
- [ ] **5. `01-DESIGN.md` presents superseded decisions as current** — `:269` still names
      Koyeb; `:156/:212/:213` still specify freshness in `/health` polled every 15 minutes,
      the opposite of the shipped code and of D-009. No `/ready` row in its API table.
- [ ] **6. S-003's third criterion depends on Sprint 2 work** — `05-BACKLOG.md:52` needs
      "the standard error shape", defined at `:151` in Sprint 2. Same defect S-005 was
      deferred for. Also `/ready` returns `status="ok"` while nothing is configured.
- [ ] **7. S-005's deferral has no decision entry**, and this file contradicted the backlog
      about it. D-011's precedent requires one for a MUST story leaving a sprint.
- [ ] **8. No Sprint 0 boundary retro.** `docs/10-FRICTION.md`'s latest entry closes one
      cost finding. Nothing records the S-005 deferral, the phase correction, D-012, D-013,
      or why S-003 and S-004 close partial. Run `retro-scribe`.
- [ ] **9. Cold start is unestablished.** `audit/COLD-START.txt` records the attempt and the
      method that would settle it: read Vercel's runtime logs for the cold-start flag on the
      request id rather than inferring from latency.
- [ ] **10. Smaller confirmed contradictions.** `docker-compose.yml:3` claims PostgreSQL
      18.4 pinned to Neon; preflight observes 18.1. `api/vercel.json` ships
      `git diff --quiet HEAD^ HEAD ./` while the friction log records testing `-- api/` —
      cwd-dependent, and not the string that was tested. `api/app/db/session.py:6` asserts
      pooling that nothing enforces and that is currently false (a `-pooler` validator is
      three lines; precedent at `core/config.py:45`). `03-QUALITY.md:51` claims CI runs
      integration tests; CI provisions no database. `04-PLAN.md:46` still says Koyeb.

- [ ] **13. The reversibility harness is inert where the gate is actually enforced.**
      Opened by the review of item 2. `.github/workflows/ci.yml` has no `services:` block and
      never sets `PREEMPT_TEST_DATABASE_URL`, so in CI the eleven integration tests skip and
      `verify.sh` still reports `PASS pytest`. Reproduce with
      `cd api && env -u PREEMPT_TEST_DATABASE_URL uv run pytest tests/test_reversibility.py`
      → `18 passed, 11 skipped`, exit 0. The skip is loud (`-ra`) and it is not a pass.
      `ci.yml:3` asserts that green locally and green in CI cannot diverge; that was true
      until this deliverable, which is the second environment-divergence instance in the
      project after `grep -P`. Same root as item 10's `03-QUALITY.md:51` claim, and the fix
      is the same one: provision a database in CI, or stop claiming CI runs integration tests.

- [ ] **12. Parser hardening on `check-probes.py` is open-ended, and should be treated as
      such.** Five review rounds found six shapes that fooled the scanner — argument
      position, keywords as arguments, brace expansion, backslash continuation, heredoc
      terminator forms, ANSI-C quoting. Each was real and each was fixed, but the rate has
      not fallen, and the reviewer's own note is "expect a sixth to exist". This is not a
      defect to close; it is a property of hand-parsing shell. The mitigations that matter
      are already in place — every fixed shape is a permanent case, and the docstring says
      the list is what is known rather than a bound. Do not spend further rounds hunting
      shapes unless one is found in a `preflight.sh` anyone would actually write.

- [ ] **11. `DOC_PHASES` in `scripts/verify.sh` has drifted from the template's.** The
      template lists `2:docs/SERVICES.md` and `5:docs/10-FRICTION.md`; preempt's lists
      neither, so `docs/SERVICES.md` is never placeholder-scanned or length-checked by §1
      even though §4 depends on it entirely. Pre-existing, found by the review of item 1 and
      deliberately not folded into it. Both files exist and are substantial, so adding the
      rows should be green — verify rather than assume.

**Done from the review:** `httpx2` removed (unused, confusable, four days old);
`docs/.phase` corrected 5 → 4; stale `uv` failure claims removed; `Superseded by` markers
added to D-003, D-007, D-008; the cold-start box unticked with its command recorded.

**Owner-blocked, not loop-blocked** — leave unticked and move on: `PREEMPT_DATABASE_URL`,
an uptime-monitor account, and the 24-hour CU-hours window.

## Current position

**Phase 4 complete** (`docs/.phase` = 4). All planning documents are written. Sprint 0 is
in progress.

| Story | State |
|-------|-------|
| S-001 gate is real and runs in CI | **Not done.** The gate runs in CI structurally, but no artifact anywhere records the red run. `03-QUALITY.md` DoD 2 requires that output on record and `docs/DEMO.md` explicitly refuses to hold it — a criterion and its deliverable contradicting each other |
| S-002 database provisioned, migrations reversible | **Partial.** Reversibility is now established by a harness that compares schemas, and is proven able to fail (D-015, `audit/REVERSIBILITY.txt`) — but it covers nothing until S-010, and it says so. Still open on this story: the Neon project, and the Neon-branch test database that was replaced by a local container with no ADR |
| S-003 health endpoint reporting freshness | **Partial.** `/health` and `/ready` split per D-009; `/ready` still returns nulls because no tables exist yet |
| S-004 live on the public internet | **Partial.** Serving over HTTPS since `43673c8`; one of six acceptance criteria met — see below |
| S-005 seed script | **Deferred into Sprint 1** (docs/05-BACKLOG.md). Needs a decision entry — BLOCK item 7 |

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
4. Close Sprint 0: the BLOCK list above, then `retro-scribe`, then `work-breaker` PASS (D-013). S-005 is deferred, not pending.
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
- ~~`docs/09-LEARNING.md` is still empty.~~ **False since `6892896` (2026-07-28).** It is
  128 lines. The claim survived eighteen hours because the gate lists that file at phase 5
  while `docs/.phase` is 4, so nothing ever opens it — and it was still being repeated into
  agent briefs today. Found by `retro-scribe`.
- **Nothing automated ever runs `scripts/preflight.sh`** — not CI, not the gate. §4 checks
  only that `audit/PREFLIGHT.txt` exists, so a recorded `PREFLIGHT: FAIL` passes the gate.
  This is deliberate (network probes make a Stop hook flaky, and a flaky gate gets switched
  off — D-014 records why gating on a green run was not adopted), but it means probe
  *reachability* is proven only when someone runs preflight by hand. If that proof should
  be automatic, CI is the place, not the Stop hook.

## Conventions that are easy to get wrong

- Never `sleep` in a shell command on this machine — a hook blocks it. Use `command sleep`
  or, better, do not poll at all.
- **Re-run the gate after the last edit, not the last interesting edit.** Item 2 was
  committed with the gate last run several edits earlier — "docstrings and markdown only",
  and it was labelled unverified rather than checked. The Stop hook caught what it missed:
  a placeholder connection string, `u:p@ep-x.<provider>.tech`, tripping section 2's
  credential scanner, which cannot tell a convincing placeholder from a real credential and
  should not try. Use `example.com` and `user:password` in any URL that must look remote.
  If something concurrent makes a gate run unsafe — an agent mid-mutation-test — wait for
  it. Deferring the gate and labelling the gap is not the same as running it.
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
