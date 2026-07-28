<!-- TEMPLATE:UNFILLED — delete this line once this document is genuinely filled in. -->
# Build plan

Phase 4. The last document before code. Turns `01-DESIGN.md` into a sequence of sprints,
each one small enough to finish, demo, and review.

## Sprint rhythm

Every sprint ends the same way, and the order is not negotiable:

1. All stories meet the Definition of Done in `03-QUALITY.md`
2. `./scripts/verify.sh` passes, output recorded
3. Demo — the thing actually runs and is shown working
4. Adversarial review; MUST-FIX items resolved
5. `docs/.phase` bumped if the sprint completed a phase
6. **Hard stop.** The next sprint does not start without an explicit go-ahead.

That hard stop is the point of the whole plan. It is what keeps a build from drifting
five sprints away from what was designed before anyone notices.

## Sprints

<!-- Keep each sprint to a coherent, demoable slice. If a sprint cannot be demoed,
     it is a task list, not a sprint — resplit it. -->

### Sprint 0 — Foundations

**Goal:** the skeleton runs, the gate is green at the current phase, and every later
sprint has somewhere to land.

- [ ] Stack chosen and recorded in `02-DECISIONS.md`
- [ ] Repository initialized, private, repo-local git identity set
- [ ] `scripts/verify.sh` stack section filled in and passing
- [ ] CI setup block uncommented in `.github/workflows/ci.yml`, gate running on every push
- [ ] `.env.example` lists every variable the app reads
- [ ] Migration tooling in place; forward-only policy recorded
- [ ] Seed script rebuilds the demo dataset from scratch — this is the backup strategy
- [ ] Test database separate from the development database
- [ ] Health endpoint live locally

**Demo:** the app boots, the health endpoint responds, CI is green at phase 4.

<!-- "Green" means green for the phase in docs/.phase — not every document filled.
     06-LEARNING is due at phase 5 and 08-CASE-STUDY at phase 8; requiring them here
     would make Sprint 0's own acceptance criterion unreachable. -->

**Advances `docs/.phase` to:** 4 <!-- documents through the plan are complete -->

### Sprint 1 — <name>

**Goal:**

| Story | Acceptance criteria | Priority |
|-------|---------------------|----------|
| | | MUST |

**Demo:**

<!-- Repeat per sprint. -->

## Sequencing

<!-- Why the sprints are in this order. Name the dependencies — what must exist before
     what. This is the section that catches "sprint 4 assumes state sprint 2 never built." -->

## Risks

<!-- What could derail this plan, how it would be noticed, and what happens then. -->

| Risk | Early signal | Response |
|------|--------------|----------|
| | | |

## Deferred

<!-- Things consciously pushed out of this plan, with the reason. Keeps the difference
     between "not built yet" and "decided against" visible. -->

-
