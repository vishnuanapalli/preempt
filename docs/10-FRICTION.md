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

> **The enforcement clause above is superseded and was itself defective — see D-014
> (2026-07-29).** The rule is right; the mechanism it prescribes is the *second* unfailable
> implementation. Building `probe_src` from the helper-call lines and substring-matching the
> service name still matches the *label text* on those lines, so `Vercel` was satisfied by
> `pass "npx (runs vercel cli)"` and `Docker` by a postgres failure message — every Vercel
> probe could be deleted with the gate still green, demonstrated 2026-07-29. Anchoring the
> pattern to the start of a line also hid every probe written as a `case` arm or `&&` chain.
> Applied literally to a new project this reproduces the defect. The mechanism that works:
> a machine-read probe id in **argument position**, with comments and quoted spans stripped
> before scanning, plus a mutation test inside the gate that proves the check can fail.

*This entry is a correction to a rule that would have misled, not the Sprint 0 boundary
retro. That retro is still owed — it is BLOCK item 8 — and the third recurrence of this one
defect class is the most valuable thing it has to record.*

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

---

## 2026-07-29 — Cost finding closed

`ignoreCommand` shipped in `e21262f`; 9 of the previous 10 commits would have been skipped.
Verified by running the exact command against real commits before it shipped, both
directions — `43673c8` (touched `api/`) exits 1 and builds, docs-only commits exit 0 and
skip.

Worth recording that the first test run was read wrong: `scripts/` and `docs/` sit at the
repository root, not under `api/`, so commits reported as "should build" were correctly
skipping. The command was right and the expectation was wrong — the same shape as ledger
R5, caught this time because the exit codes were checked against named commits instead of
assumed. → **Rule already exists (R5); this is evidence it works when actually applied.**

Trade-off accepted: an empty commit can no longer force a redeploy, which was the technique
used on `ad5913e` to pick up an environment variable. `npx vercel@latest redeploy` replaces
it, recorded in STATUS.md under conventions rather than left to be rediscovered.

---

## 2026-07-29 — Sprint 0 BLOCK item 2, and what the fix for it imported

Covers the reversibility harness that replaced S-002's round-trip criterion (D-015):
`api/tests/reversibility.py`, `api/tests/test_reversibility.py`,
`scripts/sabotage-reversibility.sh`, `audit/REVERSIBILITY.txt`.

**One thing bounds everything below.** At the time this was written none of that work was
committed — `git status` shows four new files and nine modified against `b5120b9` (13:16),
the last commit of the day. BLOCK item 1, the same defect class one round earlier, left
eight commits between 02:21 and 03:12, one per review round, so its five rounds are
countable by anyone who looks. Item 2 leaves none. "Written, verified green, and believed
done twice before the review" is therefore unverifiable from disk, and so is the review
verdict itself (reported as 5 BLOCK / 5 MAJOR / 8 MINOR). Two of those findings are
traceable — `audit/REVERSIBILITY.txt` §4(c) and (d) both say "Found by the adversarial
review, not by this matrix" — the other sixteen exist only in conversation. → **The rule
already exists and was not followed:** `STATUS.md:23`, the loop's own instruction, says
"Commit and push each iteration". No machine can tell one correct large commit from one
blob that hid three rounds, so there is no enforcement point to add. The gap is compliance,
and this is its first recorded instance. It is also why the ledger's "nothing measures
process cost" stays open: item 1 and item 2 are a clean A/B, and the difference is commits.

### The trigger condition for eight artifacts is a story that does not exist

The harness's expiry is pinned to story **S-006**. There is no S-006.

```
$ grep -n '^### S-0' docs/05-BACKLOG.md
26:S-001  37:S-002  60:S-003  67:S-004  94:S-005  112:S-010  120:S-011  [abridged]
$ git log --all -S"S-006" -- docs/05-BACKLOG.md docs/04-PLAN.md docs/01-DESIGN.md
(no output — S-006 has never appeared in any of those documents, in any commit)
```

The story that adds the schema is **S-010 — Core schema**, `05-BACKLOG.md:112`. `S-006`
appears in eight places across six files: `02-DECISIONS.md:730`, `:755`, `:778`;
`05-BACKLOG.md:53`; `STATUS.md:87`; `audit/REVERSIBILITY.txt:144`;
`api/tests/reversibility.py:49`; and `api/alembic/versions/cdf9e1c21ca7_baseline.py:25`.
Its origin is `STATUS.md:87`, written at 13:16 in `b5120b9` when the item was scoped; every
later artifact copied it, and none checked it against the backlog.

Not cosmetic. The xfail on `test_the_round_trip_covers_at_least_one_schema_object` is
strict, so the day the schema lands the suite goes red and the fix is to delete the marker —
and the instruction that tells the next person so points at a story they will not find. The
same wrong id is in the migration docstring, and in the audit artifact D-015 cites as its
evidence.

→ **Rule: an identifier that points into another document is verified against that document
when first written, and never re-established by copying.** Enforcement exists and is cheap:
require every `S-0[0-9][0-9]` in a tracked file to appear as a `### S-0[0-9][0-9]` heading in
`docs/05-BACKLOG.md`. Offline, deterministic, no network — the standard `verify.sh` §4 sets
for itself. It belongs in §4 beside the check that binds `SERVICES.md` to `preflight.sh`:
same shape, different manifest.

### Eleven tests that do not run where the gate is enforced

```
$ cd api && env -u PREEMPT_TEST_DATABASE_URL uv run pytest tests/test_reversibility.py
..................sssssssssss                                            [100%]
SKIPPED [4] tests/test_reversibility.py:366: PREEMPT_TEST_DATABASE_URL is unset, so
  migration reversibility is UNPROVEN here.   [abridged: seven further SKIPPED lines]
18 passed, 11 skipped in 0.25s     # exit 0
```

`.github/workflows/ci.yml` has no `services:` block and never sets
`PREEMPT_TEST_DATABASE_URL`, so that is exactly what CI runs; `verify.sh:234` turns exit 0
into `PASS pytest`. The whole deliverable — the round trip, the class coverage, the skip
check, the three sabotage migrations — is inert in the one place the gate is enforced on
every push.

`ci.yml:3` states: "CI runs exactly the same gate you run locally, so 'green on my machine'
and 'green in CI' cannot diverge." That was true until today. `git grep -n 'mark.integration'
HEAD -- api/` returns nothing, so before this deliverable no test in the repo could skip.
Eleven now can, and the comment became false in the single dimension it is about. D-015
records that CI skips reversibility and BLOCK item 10 already tracks `03-QUALITY.md:51`
("Tests | pytest, unit + integration | yes"); neither notices that `ci.yml` makes the claim
in its own header.

This is the second instance of the gate disagreeing with itself across environments. The
first is in `09-LEARNING.md` — `grep -P` matching nothing on macOS while working in CI — and
its lesson is written into `verify.sh:69`: "a gate that silently disagrees with itself across
environments is worse than no gate." Same disagreement, opposite direction; this time the
local run is the strong one, which is why it reads as safe and is not.

→ **Rule: a test that skips where the gate is enforced is not enforced there. Adding a test
class that needs a service either provisions that service in CI in the same commit, or
corrects every document claiming CI coverage in the same commit.** Enforcement point:
`.github/workflows/ci.yml` — a `services:` block on the same `timescaledb-oss` image
`docker-compose.yml` pins, plus `PREEMPT_TEST_DATABASE_URL`. That deletes the blind spot
instead of documenting it, and it is the answer `STATUS.md:279` already reaches for on the
preflight version of this problem ("If that proof should be automatic, CI is the place, not
the Stop hook").

### The recognition test was applied to one criterion; its twin is six lines below a gate hole

`b5120b9` proves the shape is visible from wording alone, before any code exists —
`STATUS.md:81` frames it as "the useful question is not 'is the migration reversible' but
'what would a round-trip that proves nothing look like, and does this one look like that'."
That worked. It was then applied to exactly one line. Under S-010, `05-BACKLOG.md:118` still
reads:

```
- [ ] Migration reversible against a real database
```

— the criterion just retired, restated one sprint later, satisfiable by precisely the
evidence D-015 rejects. The same document already contains the correct form twice: `:34`
"Deliberately breaking lint turns CI red; this is verified once, by doing it", and `:145`
"a test proves the count can differ from the input length". Both shapes are in one file, so
this is an application gap, not a knowledge gap. Forty-seven unticked criteria remain and
only S-002's has been through the question.

→ **Rule: every acceptance criterion names the observation that would make it false. A
criterion satisfiable by a command exiting 0 is rejected when written, not when reviewed.**
**No automated enforcement exists, and none is proposed** — a gate cannot distinguish a
falsifiable sentence from an unfalsifiable one, and the string heuristics that could try are
the flaky class §4 rejects on principle. What is enforceable is bounded and worth doing: one
sweep of the forty-seven open criteria, its result recorded in the backlog, plus a standing
line in the `work-breaker` brief. Stated plainly rather than inventing a hook.

### The proof that a check can fail left the gate, for the second time in two days

D-014 §3 put the probe check's failability inside the gate — `scripts/test-probe-gate.py`
runs at `verify.sh:316`, on every invocation. D-015 deliberately did not: "The mutation
script is not in the gate. It edits a tracked file in place." Three sabotage migrations run
in-suite; the seventeen-case matrix runs by hand.

```
$ grep -rn "sabotage-reversibility" --exclude-dir=.git .
docs/02-DECISIONS.md
audit/REVERSIBILITY.txt
```

Nothing in `verify.sh`, `.github/`, or `docs/07-RUNBOOK.md` refers to it — not even the
runbook. The reasoning for keeping it out of the gate is sound and stands. The consequence
is the one `STATUS.md:274` already records for preflight ("Nothing automated ever runs
`scripts/preflight.sh` — not CI, not the gate"), now with a second instance created the same
day, and this one is weaker: §4 at least checks `audit/PREFLIGHT.txt` exists, while nothing
checks `audit/REVERSIBILITY.txt` at all. Both artifacts carry a date — `PREFLIGHT.txt:2`
"2026-07-29 14:24", `REVERSIBILITY.txt:1` "2026-07-29" — and neither names the commit it was
produced against, so neither can be told apart from a copy that has since gone stale.

→ **Rule: a proof that runs only by hand becomes a claim on the first day nobody runs it.
Stamp its artifact with the commit it was produced against, so staleness is readable instead
of assumed.** Enforcement point: the artifact format — one line from `git rev-parse HEAD`,
written by `preflight.sh` and `sabotage-reversibility.sh` themselves — plus `work-breaker`
comparing it to the branch head at each boundary. Not the Stop gate: D-014 rejected gating
on those artifacts being green, for reasons that have not changed. This adds nothing to the
gate and makes a manual proof auditable, which is the most that is honestly available here.

### A claim in this retro's own brief was false, and the gate could not see it

The brief commissioning this entry stated that `docs/09-LEARNING.md` is "currently empty, due
at phase 5". It is 129 lines and has been since `6892896` (07-28 20:19), amended in
`7839c9f` (20:33) — three post-incident notes, including the two the ledger's R5 was earned
from. The claim's source is `STATUS.md:273`, "**`docs/09-LEARNING.md` is still empty** and
becomes due at phase 5", in a live gaps list rather than a struck-through one.

Nothing caught it in the eighteen hours and five review rounds since. `verify.sh` §1 checks
presence, template placeholders, and a ten-line floor, and only for documents due by the
current phase; `docs/.phase` is `4` and `09-LEARNING.md` is listed at phase 5, so the gate
never opens the file. This is ledger R7 in a new location — a status *file* rather than a
status hook — and it did real work: it propagated into the task that produced this entry.

→ **Rule: STATUS.md may not assert the contents of a file it does not quote. "X is empty" is
a claim with a one-command check; run it or delete the line.** Enforcement is structural, not
machine: delete the assertion, and let `verify.sh` §1's output be the only statement about
document completeness — the same move the 2026-07-28 entry made for pasted live values. A
string heuristic for "is still empty" would be the flaky class §4 rejects, so none is
proposed.

### What holds up

D-015 and `audit/REVERSIBILITY.txt` are the strongest artifacts this project has produced
against their own subject. §4 of the audit file records six holes the work found in itself
and credits two of them to the reviewer rather than to its own matrix; "What this does not
establish" names row data, grants, ownership, TimescaleDB objects and branched histories as
unchecked rather than leaving them to be discovered; the one criterion ticked
(`05-BACKLOG.md:44`) says in its own text that it covers nothing today and names the day it
starts to. Nothing in this entry contradicts that work. Every finding above is about what
the deliverable did *not* reach: the sibling criterion, the CI environment, the pointer it
copied, and the record of how long it took.

### Ledger candidates from this entry

- **Skips are not passes, and a test that skips where the gate runs is not enforced there.**
  Second instance of environment-divergent gate behaviour in this project. Generalises;
  proposed as a new standing rule.
- **A manual proof needs a stamped artifact or it decays to a claim.** Second instance in two
  days. Generalises; proposed as a new standing rule, or as a clause on R2.
- **Cross-document identifiers are verified once and never re-established by copying.** New
  evidence for R4 (verify, do not recall) in a form R4 does not currently cover — the id was
  not recalled from training, it was invented in a status note and then trusted six times.
- **R7 extends to status files, not only status displays.** Evidence above; no new rule
  needed.
- **Not a candidate:** the falsifiable-criterion rule. It is real and load-bearing, but it
  has no enforcement point anywhere, and the ledger's own thesis is that a rule without one
  is a wish. It stays here until the backlog sweep gives it a home.
