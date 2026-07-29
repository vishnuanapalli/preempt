# Friction log

How the *work* went, as opposed to how the product turned out. Product defects belong in
`09-LEARNING.md`; this file records process cost — wasted cycles, blocked-on-access, and
claims that steered the work wrongly.

Written by the `retro-scribe` agent at phase and sprint boundaries. `work-breaker` checks
it exists and is actionable; an entry with no rule and no enforcement point named is a
finding against the scribe, not a contribution.

Entries that generalise beyond this project get promoted to `~/.claude/PROCESS-LEDGER.md`.

---

## 2026-07-28 — Sprint 0, the Vercel 404

**Wasted cycles: 3 deployments, across 2 sessions.** Each cycle changed one piece of
configuration and waited for a remote build. A local `vercel build` rooted at `api/`
exposed the cause — an empty output directory with zero functions — in seconds. The
configuration was never wrong in the way being guessed at; no Python builder was running
at all. → **Rule: reproduce a remote build locally before changing its configuration a
second time.** Promoted as ledger R3. Enforced by `project-preflight` §5 and by the `uv`
floor probe, since local reproduction is impossible below it.

**Discovered-while-blocked access: three instances.** The Vercel CLI's auth state, the
`uv` version floor, and the Neon connection string were each needed mid-debug and none was
inventoried. The auth state was additionally *misdiagnosed* — an `npx` package download
was read as a login prompt, producing an instruction to run `vercel login` when the CLI
was both installed-on-demand and already authenticated. → **Rule: inventory and probe
every service before depending on it; verify an invocation before handing it over.** Ledger
R1 and R4. Enforced by `docs/SERVICES.md` + `scripts/preflight.sh`.

**Two unverified claims steered the work.** `STATUS.md` carried "dependencies may never
install" as the leading hypothesis when the build log had already shown `uv` resolving
`uv.lock` successfully; and it recorded `{"python": 2}` as unchanged across three
deployments when the third reported no functions at all. The second was the expensive one:
it merged two distinct failures into one and aimed the investigation at entrypoint syntax
instead of builder selection. → **Rule: record a signal as changed or unchanged only after
comparing actual values.** Ledger R5.

**The gate was green throughout.** `verify.sh` passed — ruff, mypy, pytest, document
presence — while every deployed route returned 404. Nothing in the gate could observe the
running system. → **Rule: a gate that cannot fail when the product is broken is not a
gate.** Ledger R2. Partly addressed: `preflight.sh` now probes the deployed app and
distinguishes a FastAPI 404 from a platform 404. Not fully addressed: the probe is not in
the Stop gate, deliberately, because network checks there would be slow and flaky.

**A probe was written that measured the wrong thing.** The first version of the Python
check read system `python3` (3.13) and reported a failure that did not exist, while the
suite was passing on uv's 3.12 venv. Caught on the first run, but it is the same class as
everything above. → **Rule: a probe must print the value it observed, and the value must
be the one that matters.** Enforced by review of `preflight.sh`, not by a machine.

**Not measured:** wall-clock cost of the three deploy cycles, and how much of the session
went to the blocker versus to building. Nothing records this, so improvement can be
asserted but not shown. Open finding in the ledger.

---

## 2026-07-28 — The process system itself, and an audit of the entry above

First actual run of `retro-scribe`; the entry above was written by hand. Covers `43673c8`
through `8b2d2a7` — the work that followed the Vercel fix — and judges the earlier entry
against the same standard. Every claim below carries the command that produced it.

### The gate that checks services are probed passes on a preflight with zero probes

Section 4 of `scripts/verify.sh` reads every service row out of `docs/SERVICES.md` and
asserts each one "has a probe." The test is `key not in probe_src`, where `key` is the
first word of the service name lowercased and `probe_src` is the **entire text of
`scripts/preflight.sh`, comments included**. A one-line comment naming the services
satisfies it.

```
$ printf '#!/bin/bash\n# stub: github vercel neon docker uv\nexit 0\n' > scripts/preflight.sh
$ # ...then run section 4's embedded python against it
services checked: 6
unprobed reported by the gate: ''
VERDICT: gate would PASS on a preflight.sh with zero probes
```

This is the defect class recorded four paragraphs above — *a probe was written that
measured the wrong thing* — recurring one level up, inside the same commit (`50c8631`)
that recorded the lesson. It has already propagated: `~/Desktop/final project/_template`
was updated at 21:43 today and `grep -c "key not in probe_src"` on its `scripts/verify.sh`
returns `1`, so every project born from the template inherits it.

There is a live instance, not only a hypothetical one. `neon` appears in `preflight.sh`
exactly twice, both times inside the label string `env PREEMPT_DATABASE_URL (neon)` — a
probe of *Vercel's environment list*, not of Neon. `SERVICES.md` is honest that Neon is
"not reachable from this machine"; the gate is not, and prints `PASS every service in
SERVICES.md has a probe`.

→ **Rule: a check that a probe exists must bind to the probe's invocation, not to the
file's text.** Enforcement: build `probe_src` from only those lines that call the
`pass`/`fail`/`waive` helpers, in `scripts/verify.sh` section 4 **and** in the template's
copy. Both, or the fix does not travel.

### Two documents cite a live value that was already false when they shipped

`STATUS.md:29` pastes `{"status":"ok","environment":"local",...}` and `STATUS.md:97` calls
it "the live proof" that no environment variables are set. `docs/05-BACKLOG.md:63` repeats
it as the evidence for S-004's third acceptance criterion. Both were true when written at
20:38 (`34a8488`) and false thirteen minutes later — `ad5913e` (20:51) is an empty commit
whose whole purpose was to redeploy so `PREEMPT_ENVIRONMENT` would take effect, and it
worked.

```
$ curl -s https://preempt-tau.vercel.app/api/v1/health
{"status":"ok","environment":"production","ingest_interval_seconds":1800}
```

The project's own preflight already said so, and shipped in the same commit as the
contradiction: `audit/PREFLIGHT.txt` line 20 `PASS env PREEMPT_ENVIRONMENT set`, line 24
`PASS GET /api/v1/health HTTP 200, environment=production` — both committed in `50c8631`,
alongside a STATUS.md edit that left the stale curl untouched. The backlog line is the
worse of the two, because it is formatted as proof: an unchecked box justified by a
response the platform no longer returns. The box does belong unchecked —
`PREEMPT_DATABASE_URL` is still unset, and waived — but for a different reason than the one
written down.

This is ledger R7 ("a status display must prove the state it reports is current") violated
one minute after R7 was fixed at its source: `~/.claude/hooks/session-context.sh` has mtime
21:01, `50c8631` landed at 21:02.

→ **Rule: live values live in exactly one file. `audit/PREFLIGHT.txt` holds them; STATUS.md
and the backlog point at it and never paste command output.** Enforcement is structural,
not machine: delete the pasted values so there is nothing to go stale, and have
`work-breaker` read `audit/PREFLIGHT.txt` against STATUS.md at each boundary. No cheap gate
check exists here — staleness heuristics in a Stop hook were deliberately rejected in
`verify.sh` section 4 and that reasoning still holds. Said plainly rather than inventing an
enforcement point.

### Ten production deployments, every one of them "Ready"

The measurement the entry above calls impossible was available the whole time, from a CLI
that was already authenticated:

```
$ npx vercel@latest ls --yes
  Age   Deployment            Status      Environment   Duration
  43m   preempt-dy84crs2o...  * Ready     Production    20s
  43m   preempt-8nsizqwbk...  * Ready     Production    21s
  54m   preempt-9qh51qm3h...  * Ready     Production    22s
  60m   preempt-cz8bs0qiz...  * Ready     Production    21s
  1h    (four more)           * Ready     Production    20-23s
  2h    (two more)            * Ready     Production    29-30s
```

Ten production builds between roughly 19:45 and 21:02. Two things fall out of it.

**"Ready" carried zero information.** Ten of ten report Ready, including the three or four
that served a platform 404 on every route. The entry above says "the gate was green
throughout" about `verify.sh`; the platform's own status column was green for 100% of
deployments and never once disagreed with itself. That is ledger R2 with a number attached.

**Seven of the ten could not have changed the artifact.** `9a24c1b` (.gitignore), `7839c9f`
and `34a8488` (docs only), `50c8631` and `8b2d2a7` (docs and scripts) each triggered a full
production build. Every commit deploys, including commits that touch nothing under `api/`.

→ **Rule: a deploy trigger that fires on commits which cannot change the artifact is a
budget leak, and belongs in `SERVICES.md` as a limit like any other.** Enforcement: Vercel's
Ignored Build Step, set to skip when `git diff --quiet HEAD^ HEAD -- api/`, recorded in the
Vercel row of `docs/SERVICES.md`. Not verified: whether Hobby build minutes are anywhere
near a real ceiling — the mechanism is the finding; the budget number was not checked.

### The process system changed the definition of done with no decision entry

`grep -ciE "preflight|SERVICES|friction" docs/02-DECISIONS.md` returns `0`; the log ends at
D-010. Between 20:52 and 21:02 the session added a gate section, a services manifest, a
probe script, a friction log, a global skill (`~/.claude/skills/project-preflight/`), and
two global agents (`retro-scribe`, `work-breaker`) — work that altered what "done" means for
this project and for every future one. `CLAUDE.md` requires that every consequential choice
be a numbered entry. This one was not consequential *to the product*, which is presumably
why it was skipped, and that is exactly the gap: process changes are the ones nobody logs
and everyone inherits.

→ **Rule: a change to the gate is a decision and gets a numbered entry.** Enforcement: this
one *is* cheap, offline and deterministic, so it fits section 4's own stated constraints —
fail if `scripts/verify.sh` changed in the working tree or in the last commit while
`docs/02-DECISIONS.md` did not.

### Verdict on building the process system mid-project

It did not interrupt the debugging. The 404 was fixed at 20:30 (`43673c8`); the process
files were written from ~20:52. It paid for itself inside ten minutes — preflight's first
run surfaced a blocker nobody knew about (`uv` 0.9.18 against Vercel's 0.9.25 floor), which
is the one check that would have caught the 404 in seconds.

What it cost is narrower and real: the session ended with S-004 one step from closable and
mis-recorded instead. `PREEMPT_ENVIRONMENT` was set at 20:51; the last 45 minutes went to
process; and then the process artifact and the status document were committed together
contradicting each other. Right call, wrong stopping point — the system was built, and the
documents it exists to keep honest were never re-read against it.

### Audit of the 2026-07-28 Sprint 0 entry above

It holds up. Every finding names a rule, five of six name an enforcement point, and the
sixth ("a probe must print the value it observed") says plainly that its enforcement is
human review rather than inventing a machine check — which is the correct move, not a gap.
No padding found; nothing in it is unsupported by what is on disk. Two corrections:

- **Its one quantified claim is not reconstructable from the repo.** "3 deployments, across
  2 sessions" is a defensible count of *hypothesis-driven config guesses* — git shows two
  config-touching commits before the fix, `a14416a` and `43673c8`, plus dashboard changes
  that leave no trace — but the log does not say that is what it is counting, and the number
  the platform can actually produce is ten. The ledger already carries "nothing measures
  process cost" as an open finding; the new information is that `vercel ls` was available
  and authenticated the entire time, so the measurement was never actually missing.
- **Ledger R3's enforcement pointer is wrong.** The ledger row says `project-preflight`
  section 4; section 4 is "Write and run `scripts/preflight.sh`" and the local-reproduction
  rule is section 5. The friction entry above has it right. A one-word error, but in the
  file whose thesis is that a rule with no enforcement point is a wish — a rule pointing at
  the wrong enforcement point is the same wish with a citation.

### Two ledger "not yet done" items closed today, for the record

`retro-scribe` has now been run (this entry), and the template was ported at 21:43-21:44 —
`docs/SERVICES.md`, `docs/10-FRICTION.md`, `scripts/preflight.sh` and gate section 4 are all
present in `~/Desktop/final project/_template`. The port carries the probe-check defect
described at the top of this entry, so it is closed but not clean.
