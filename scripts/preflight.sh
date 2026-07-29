#!/usr/bin/env bash
# Preflight: prove every external dependency answers before anything is built on it.
#
# Each probe prints the value it actually observed — a version, a status code, a setting —
# not merely "ok". A probe that cannot fail is the same defect as a green badge that means
# nothing, which is the failure this whole file exists to prevent.
#
# A dependency that cannot be probed is either dropped or WAIVED here in writing, with a
# reason and the condition that lifts the waiver. Silence is not an option the script offers.
#
# Usage: bash scripts/preflight.sh | tee audit/PREFLIGHT.txt

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

if [ -t 1 ]; then G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'
else G=""; R=""; Y=""; N=""; fi

fails=0
pass()  { printf '  %sPASS%s  %-34s %s\n' "$G" "$N" "$1" "$2"; }
fail()  { printf '  %sFAIL%s  %-34s %s\n' "$R" "$N" "$1" "$2"; fails=$((fails + 1)); }
waive() { printf '  %sWAIVED%s %-34s %s\n' "$Y" "$N" "$1" "$2"; }

VERCEL="npx --yes vercel@latest"
SCOPE="vishnus-projects-2166f0a0"
APP="https://preempt-tau.vercel.app"

echo
echo "Preflight — $(date '+%Y-%m-%d %H:%M')"

# ------------------------------------------------------------------ 1. toolchain
echo
echo "1. Local toolchain"

# Probe the interpreter the project actually runs on, not whatever `python3` resolves to.
# The first version of this check read system python3 (3.13) and reported a failure that
# did not exist, while the suite was passing on uv's 3.12 venv the whole time. A probe
# that measures the wrong thing is worse than no probe: it gets ignored, and then the
# real failures next to it get ignored too.
v=$( (cd api && uv run python -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>/dev/null | tail -1) )
case "$v" in
  3.12.*) pass "project python 3.12" "$v (uv venv)" ;;
  "")     fail "project python 3.12" "uv could not resolve an interpreter" ;;
  *)      fail "project python 3.12" "found $v; pyproject requires >=3.12,<3.13" ;;
esac

# Vercel refuses to build with an older uv. The floor is a real blocker, not a preference:
# it stops the local build reproduction that ledger R3 requires.
UV_FLOOR="0.9.25"
if command -v uv >/dev/null 2>&1; then
  uvv=$(uv --version 2>&1 | awk '{print $2}')
  if [ "$(printf '%s\n%s\n' "$UV_FLOOR" "$uvv" | sort -V | head -1)" = "$UV_FLOOR" ]; then
    pass "uv >= $UV_FLOOR" "$uvv"
  else
    fail "uv >= $UV_FLOOR" "found $uvv — too old for 'vercel build' locally"
  fi
else
  fail "uv >= $UV_FLOOR" "not installed"
fi

if command -v docker >/dev/null 2>&1; then
  pass "docker" "$(docker --version 2>&1 | awk '{print $3}' | tr -d ,)"
else
  fail "docker" "not installed — local database cannot start"
fi

if command -v npx >/dev/null 2>&1; then
  pass "npx (runs vercel cli)" "node $(node --version 2>&1)"
else
  fail "npx (runs vercel cli)" "not installed — vercel cli is not installed globally"
fi

# ------------------------------------------------------------------- 2. database
echo
echo "2. Local database"

if docker compose ps --status running 2>/dev/null | grep -q preempt-db; then
  pgv=$(docker compose exec -T db psql -U preempt -d preempt -tAc 'show server_version' 2>/dev/null | tr -d '[:space:]')
  [ -n "$pgv" ] && pass "postgres reachable (5433)" "server_version $pgv" \
                || fail "postgres reachable (5433)" "container up but psql did not answer"

  ts=$(docker compose exec -T db psql -U preempt -d preempt -tAc \
       "select default_version from pg_available_extensions where name='timescaledb'" 2>/dev/null | tr -d '[:space:]')
  [ -n "$ts" ] && pass "timescaledb available" "$ts" \
               || fail "timescaledb available" "extension not offered by this image"
else
  fail "postgres reachable (5433)" "container not running — 'docker compose up -d --wait'"
fi

# ------------------------------------------------------------------ 3. source host
echo
echo "3. Source host"

if git ls-remote --exit-code origin HEAD >/dev/null 2>&1; then
  pass "github remote reachable" "$(git config --get remote.origin.url)"
else
  fail "github remote reachable" "git ls-remote failed"
fi

# ----------------------------------------------------------------------- 4. vercel
echo
echo "4. Vercel"

who=$($VERCEL whoami --scope "$SCOPE" </dev/null 2>/dev/null | tail -1 | tr -d '[:space:]')
if [ -n "$who" ]; then
  pass "vercel cli authenticated" "$who"
else
  fail "vercel cli authenticated" "whoami returned nothing — run 'npx vercel@latest login'"
fi

# Root Directory is a dashboard setting the repository cannot express, which makes it the
# one part of the deployment that can be silently lost. Probe it rather than trust it.
if [ -f .vercel/project.json ]; then
  rd=$(python3 -c "import json;print(json.load(open('.vercel/project.json')).get('settings',{}).get('rootDirectory'))" 2>/dev/null)
  [ "$rd" = "api" ] && pass "vercel rootDirectory == api" "$rd" \
                    || fail "vercel rootDirectory == api" "found '$rd' — build will produce no function"
else
  fail "vercel rootDirectory == api" "not linked — run 'npx vercel@latest pull --yes --environment production'"
fi

envs=$($VERCEL env ls --scope "$SCOPE" </dev/null 2>/dev/null)
case "$envs" in
  *PREEMPT_ENVIRONMENT*) pass "env PREEMPT_ENVIRONMENT set" "present (value not printed)" ;;
  *)                     fail "env PREEMPT_ENVIRONMENT set" "missing — /health will report 'local' in production" ;;
esac

case "$envs" in
  *PREEMPT_DATABASE_URL*) pass "env PREEMPT_DATABASE_URL (neon)" "present (value not printed)" ;;
  *) waive "env PREEMPT_DATABASE_URL (neon)" "not set; no code reads the database before Sprint 1. Waiver lifts when S-004 closes or the first query ships — whichever comes first." ;;
esac

# ------------------------------------------------------------------- 5. deployed
echo
echo "5. Deployed application"

code=$(curl -s -o /dev/null -w '%{http_code}' "$APP/api/v1/health?cb=$(date +%s)" 2>/dev/null)
if [ "$code" = "200" ]; then
  env_reported=$(curl -s "$APP/api/v1/health?cb=$(date +%s)-e" 2>/dev/null \
                 | python3 -c "import json,sys;print(json.load(sys.stdin).get('environment'))" 2>/dev/null)
  pass "GET /api/v1/health" "HTTP 200, environment=$env_reported"
  [ "$env_reported" = "production" ] || fail "health reports production" "reports '$env_reported'"
else
  fail "GET /api/v1/health" "HTTP $code"
fi

# The gate is green while every route 404s unless something checks the running system.
# This probe is that check (ledger R2).
body=$(curl -s "$APP/nope-$(date +%s)" 2>/dev/null)
case "$body" in
  *'"detail"'*) pass "unknown route served by app" "FastAPI 404, not a platform 404" ;;
  *)            fail "unknown route served by app" "platform answered — app may not be routing" ;;
esac

# ------------------------------------------------------------------- verdict
echo
if [ "$fails" -eq 0 ]; then
  printf '%sPREFLIGHT: PASS%s\n\n' "$G" "$N"
  exit 0
fi
printf '%sPREFLIGHT: FAIL (%d)%s\n\n' "$R" "$fails" "$N"
exit 1
