#!/usr/bin/env bash
#
# The gate. This script decides whether the project is green.
#
# Called by three things, all running exactly this command:
#   - the local Stop hook, via .claude/verify.sh
#   - CI, via .github/workflows/ci.yml
#   - you, by hand, before claiming any phase is done
#
# Exit 0 = green. Anything else = not done.
#
# The gate is phase-aware. A project is legitimately not finished while its documents
# are still being written, so `docs/.phase` records the highest phase completed and only
# the documents due by that phase are required. Without this the gate would be red from
# Phase 0 until the very end, and a gate that is always red gets switched off.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2

fail=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
skip() { printf '  \033[33mSKIP\033[0m  %s\n' "$1"; }

# This file necessarily contains every pattern it searches for, so it is excluded from
# its own scans. Without this the gate can never pass on any project.
SELF="scripts/verify.sh"

# Each document, and the phase by which it must be complete.
DOC_PHASES=(
  "0:docs/00-PRD.md"
  "1:docs/01-DESIGN.md"
  "2:docs/02-DECISIONS.md"
  "3:docs/03-QUALITY.md"
  "4:docs/04-PLAN.md"
  "4:docs/05-BACKLOG.md"
  "5:docs/09-LEARNING.md"
  "6:docs/06-UI-SPEC.md"
  "7:docs/07-RUNBOOK.md"
  "7:README.md"
  "8:docs/08-CASE-STUDY.md"
)

# Literal strings the template ships. A document containing any of them has not been
# written yet. Unlike a line count, this cannot be satisfied by deleting one line —
# only by actually writing the document.
PLACEHOLDERS=(
  'TEMPLATE:UNFILLED'
  '<PROJECT NAME>'
  '<short imperative title>'
  '<what happened, in one line>'
  '<capability>'
  '<outcome>'
  '<concept>'
  '<user>'
  '<name>'
  '<date>'
)

# Both patterns are passed to grep with an explicit -e. SECRET_RE begins with a hyphen,
# and without -e grep parses the pattern as an option cluster, silently matching nothing.
ATTRIB_RE='co-authored-by:[[:space:]]*claude|generated with \[?claude|claude\.ai/code|anthropic'
SECRET_RE='-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[A-Za-z0-9]{30,}|npg_[A-Za-z0-9]{16,}'

# A database URL carrying a password against a real host.
#
# Plain ERE, no `grep -P`: BSD grep on macOS has no PCRE support, so a negative
# lookahead matches nothing locally while working in CI — a gate that silently
# disagrees with itself across environments is worse than no gate.
#
# Instead the host is required to contain a letter and a dot, which excludes
# `localhost` (no dot) and `127.0.0.1` (no letters). Placeholder domains are filtered
# out afterwards by line, not by pattern.
DBURL_RE='postgres(ql)?(\+[a-z]+)?://[^:/ ]+:[^@/ ]+@[A-Za-z0-9-]*[A-Za-z][A-Za-z0-9-]*\.'

# Source files on disk, independent of git. The tracked-file scans below are blind in a
# directory that was never initialized, which is exactly the state a code-first start
# produces — so presence on disk is checked separately and is never treated as absence.
#
# The gate's own two helpers are pruned by name, not the whole of `scripts/`. Without some
# exclusion a skeleton project is red on its first run — the gate reads its own tooling as
# "source exists before phase 0", and a gate that is red before any work starts gets
# switched off. Pruning the directory instead would blind this to a project that puts
# application code under `scripts/`, which is a real shape. Section 3 lints scripts/*.py
# separately, so neither file is unchecked.
src_on_disk() {
  find . \
    -path ./.git -prune -o -path ./node_modules -prune -o \
    -path ./scripts/check-probes.py -prune -o -path ./scripts/test-probe-gate.py -prune -o \
    -path ./.venv -prune -o -path ./dist -prune -o -path ./build -prune -o \
    \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' \
       -o -name '*.go' -o -name '*.rs' -o -name '*.java' \) -print 2>/dev/null | head -1
}

# -------------------------------------------------------------------- 0. phase
echo
echo "0. Phase"

if [ ! -f docs/.phase ]; then
  bad "docs/.phase is missing — it records the highest phase this project has completed"
  echo
  echo "VERIFY: FAIL"
  exit 1
fi

phase="$(tr -d '[:space:]' < docs/.phase)"
case "$phase" in
  skeleton)
    pass "skeleton — no documents due yet" ;;
  0|1|2|3|4|5|6|7|8)
    pass "phase $phase complete — documents through phase $phase are required" ;;
  *)
    bad "docs/.phase says '$phase' — expected 'skeleton' or a number 0-8"
    echo
    echo "VERIFY: FAIL"
    exit 1 ;;
esac

SRC="$(src_on_disk)"

# The phase must be consistent with what is on disk. Code present while the phase still
# says "skeleton" is the code-before-documents violation this process exists to prevent,
# and it is also the state in which every git-based scan below sees nothing.
if [ "$phase" = "skeleton" ] && [ -n "$SRC" ]; then
  bad "source files exist (e.g. $SRC) but docs/.phase still says 'skeleton'"
fi

# ---------------------------------------------------------------- 1. documents
echo
echo "1. Document gate"

due=0
for entry in "${DOC_PHASES[@]}"; do
  doc_phase="${entry%%:*}"
  doc="${entry#*:}"

  [ "$phase" = "skeleton" ] && continue
  [ "$phase" -lt "$doc_phase" ] && continue
  due=$((due + 1))

  if [ ! -f "$doc" ]; then
    bad "$doc is missing (due by phase $doc_phase)"
    continue
  fi

  found=""
  for ph in "${PLACEHOLDERS[@]}"; do
    if grep -Fq "$ph" "$doc"; then found="$ph"; break; fi
  done

  if [ -n "$found" ]; then
    bad "$doc still contains the template placeholder \"$found\""
  elif [ "$(wc -l < "$doc")" -lt 10 ]; then
    bad "$doc is under 10 lines — not a real document yet"
  else
    pass "$doc"
  fi
done

[ "$due" -eq 0 ] && skip "no documents due at phase '$phase'"

# ------------------------------------------------- 2. attribution and secrets
# No tracked file may reveal how the code was written, and no tracked file may carry
# a credential. Tracked files only, so gitignored local tooling is out of scope.
echo
echo "2. Attribution and secret gate"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1 || [ -z "$(git ls-files 2>/dev/null)" ]; then
  # Nothing is tracked, so nothing can be scanned. That is fine for an empty skeleton and
  # unacceptable once code exists — an unscannable project must never report green.
  if [ -n "$SRC" ]; then
    bad "source files exist but nothing is tracked in git — no file can be scanned"
  else
    skip "nothing tracked yet — no files to scan"
  fi
else
  hits=$(git ls-files -z 2>/dev/null \
    | xargs -0 grep -IliE -e "$ATTRIB_RE" 2>/dev/null | grep -vxF "$SELF" || true)
  if [ -n "$hits" ]; then
    bad "attribution trace found in tracked files:"
    printf '%s\n' "$hits" | sed 's/^/          /'
  else
    pass "no attribution trace in tracked files"
  fi

  # %B is the body only. A commit authored as "Claude <noreply@anthropic.com>" leaves
  # no trace there, and the author line renders on every commit page — the most visible
  # possible leak. --all so a trace on any branch is caught, not just the current one.
  if git log --all --format='%an %ae %cn %ce %B' 2>/dev/null | grep -qiE "$ATTRIB_RE"; then
    bad "attribution trace found in commit author, committer, or message"
  else
    pass "no attribution trace in commit history"
  fi

  secrets=$(git ls-files -z 2>/dev/null \
    | xargs -0 grep -IliE -e "$SECRET_RE" 2>/dev/null | grep -vxF "$SELF" || true)
  if [ -n "$secrets" ]; then
    bad "possible credential found in tracked files:"
    printf '%s\n' "$secrets" | sed 's/^/          /'
  else
    pass "no credential pattern in tracked files"
  fi

  # Reported by line, so documentation placeholders can be filtered without weakening
  # the pattern itself.
  dburls=$(git ls-files -z 2>/dev/null \
    | xargs -0 grep -InIE -e "$DBURL_RE" 2>/dev/null \
    | grep -vE 'example\.(com|org|net)|@db[:.]|USER:PASSWORD|user:password' \
    | grep -v "^${SELF}:" || true)
  if [ -n "$dburls" ]; then
    bad "database URL with a password against a real host, in tracked files:"
    printf '%s\n' "$dburls" | cut -c1-100 | sed 's/^/          /'
  else
    pass "no database credential in tracked files"
  fi
fi

# -------------------------------------------------------------------- 3. stack
# Filled in at Sprint 0 (story S-001). These are the project's real commands, not a
# stub — a gate that echoes a placeholder while sprints get signed off against it is
# item 1 on the never-ship list, and it is the failure that actually happened in prior
# work in this domain.
echo
echo "3. Stack gate"

ran_any=0

if [ -f api/pyproject.toml ]; then
  ran_any=1
  if command -v uv >/dev/null 2>&1; then
    ( cd api && uv run ruff check . )   && pass "ruff"   || bad "ruff"
    ( cd api && uv run ruff format --check . ) && pass "format" || bad "format"
    ( cd api && uv run mypy app )       && pass "mypy"   || bad "mypy"
    ( cd api && uv run pytest )         && pass "pytest" || bad "pytest"

    # The gate's own python runs inside the gate, so a defect there weakens every check
    # around it while still reporting green. It is held to the same standard as the
    # application's, on the same tool versions from api's lockfile — no second environment.
    if ls scripts/*.py >/dev/null 2>&1; then
      ( cd api && uv run ruff check ../scripts )          && pass "ruff (scripts)"   || bad "ruff (scripts)"
      ( cd api && uv run ruff format --check ../scripts ) && pass "format (scripts)" || bad "format (scripts)"
      ( cd api && uv run mypy ../scripts )                && pass "mypy (scripts)"   || bad "mypy (scripts)"
    fi
  else
    bad "api/pyproject.toml present but uv is not installed"
  fi
fi

if [ -f frontend/package.json ]; then
  ran_any=1
  if command -v npm >/dev/null 2>&1; then
    ( cd frontend && npm run --silent lint )      && pass "lint"      || bad "lint"
    ( cd frontend && npm run --silent typecheck ) && pass "typecheck" || bad "typecheck"
    ( cd frontend && npm run --silent test )      && pass "test"      || bad "test"
  else
    bad "frontend/package.json present but npm is not installed"
  fi
fi

if [ "$ran_any" -eq 0 ]; then
  # A skip is not a pass. If source exists, an unconfigured stack gate is a failure,
  # not an absence — otherwise the project goes green having never run a test.
  if [ -n "$SRC" ]; then
    bad "source files exist but no stack checks are configured — fill in section 3"
  else
    skip "no stack yet — fill this section in at Sprint 0"
  fi
fi

# ------------------------------------------------------------------ 4. process
# The process record is a deliverable and rots like any other. These checks are
# deliberately cheap, offline, and deterministic: they read artifacts on disk and never
# touch the network. Putting the live probes here instead would make the gate slow and
# flaky, and a flaky gate gets switched off — which is a worse outcome than no gate.
#
# What this therefore does NOT check, stated rather than left to be discovered:
#   - whether the last preflight run was green (read audit/PREFLIGHT.txt)
#   - whether the friction log is fresh for the current phase
#   - whether a probe that exists is ever REACHED. The coverage check reads the source, so
#     a probe moved into a function nobody calls, an `if false` branch, or a block below
#     `exit 0` still counts. `check-probes.py --emitted` is what proves reachability and
#     preflight.sh asserts it on every run — but nothing automated runs preflight, so in
#     practice that proof exists only when someone runs it by hand.
# All three are work-breaker's job at phase boundaries.
echo
echo "4. Process gate"

if [ ! -f docs/SERVICES.md ]; then
  bad "docs/SERVICES.md missing — external dependencies are not inventoried"
elif [ ! -f scripts/preflight.sh ]; then
  bad "scripts/preflight.sh missing — services are listed but nothing probes them"
elif [ ! -f scripts/check-probes.py ]; then
  bad "scripts/check-probes.py missing — nothing binds the manifest to the probes"
else
  # Every service named in the manifest must be probed, unless the row says it is not
  # provisioned yet. A service depended on but never probed is the most expensive defect
  # class in this workspace.
  #
  # The check itself lives in scripts/check-probes.py, so that the gate, preflight's own
  # coverage assertion, and the mutation test below all exercise one implementation rather
  # than three that can drift. Read that file for how the binding works and what it still
  # cannot see.
  # stdout only on the success path: folding stderr in prints interpreter noise inside a
  # green PASS line, which is the same "noise treated as content" shape that once let a
  # SyntaxWarning be parsed as a probe id. Failure re-runs with stderr, since that is the
  # rare path and the diagnostics matter there.
  if probes=$(python3 scripts/check-probes.py --static 2>/dev/null); then
    pass "$probes"
  else
    bad "probe coverage:"
    python3 scripts/check-probes.py --static 2>&1 | sed 's/^/          /'
  fi

  # And the check that the check can fail. Two earlier versions of the probe check shipped
  # unfailable, so its failability is itself gated rather than asserted.
  if [ -f scripts/test-probe-gate.py ]; then
    if mutation=$(python3 scripts/test-probe-gate.py 2>/dev/null); then
      pass "$mutation"
    else
      bad "the probe check does not fail when it should:"
      python3 scripts/test-probe-gate.py 2>&1 | sed 's/^/          /'
    fi
  else
    bad "scripts/test-probe-gate.py missing — nothing proves the probe check can fail"
  fi

  if [ -f audit/PREFLIGHT.txt ]; then
    pass "preflight has been run and recorded"
  else
    bad "audit/PREFLIGHT.txt missing — preflight was never actually run"
  fi
fi

if [ -s docs/10-FRICTION.md ]; then
  pass "friction log present"
else
  bad "docs/10-FRICTION.md missing or empty — retro-scribe has not recorded this phase"
fi

# ------------------------------------------------------------------- verdict
echo
if [ "$fail" -eq 0 ]; then
  echo "VERIFY: PASS"
else
  echo "VERIFY: FAIL"
fi
exit "$fail"
