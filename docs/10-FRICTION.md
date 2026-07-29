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
