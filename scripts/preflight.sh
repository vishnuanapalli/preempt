#!/usr/bin/env bash
# Preflight: prove every external dependency answers before anything is built on it.
#
# Each probe prints the value it actually observed — a version, a status code, a setting —
# not merely "ok". A probe that cannot fail is the same defect as a green badge that means
# nothing, which is the failure this whole file exists to prevent.
#
# Every outcome names the probe it belongs to as its first argument, unquoted:
#
#     pass vercel:auth "vercel cli authenticated" "$who"
#          ^^^^^^^^^^^ declared in the Probe column of docs/SERVICES.md
#
# That id is the binding between the manifest and this file, and it is checked both ways:
# `scripts/check-probes.py --static` runs in the gate and requires every declared probe to
# exist here; the verdict below requires every declared probe to have actually run. The
# earlier arrangement matched service names against probe *labels*, which meant deleting
# every Vercel probe still reported full coverage.
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

# Outcomes record their probe id as well as printing it, so the verdict can assert that
# every declared probe ran. A probe sitting in a branch nobody takes prints nothing and is
# invisible to the static check — this is what catches that.
SEEN=$(mktemp) || exit 1
trap 'rm -f "$SEEN"' EXIT

pass()  { printf '%s\n' "$1" >>"$SEEN"
          printf '  %sPASS%s   %-23s %-30s %s\n' "$G" "$N" "$1" "$2" "$3"; }
fail()  { printf '%s\n' "$1" >>"$SEEN"
          printf '  %sFAIL%s   %-23s %-30s %s\n' "$R" "$N" "$1" "$2" "$3"
          fails=$((fails + 1)); }
# A waiver satisfies coverage and does not fail the run — that is what a waiver is for.
# It is counted and named in the verdict because otherwise swapping a real probe for a
# one-line `waive` is green in every check and silent: the cheapest way to fake this file.
waive() { printf '%s\n' "$1" >>"$SEEN"
          printf '  %sWAIVED%s %-23s %-30s %s\n' "$Y" "$N" "$1" "$2" "$3"
          waived="${waived:-0}"; waived=$((waived + 1)); WAIVED_IDS="${WAIVED_IDS:-} $1"; }

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
  3.12.*) pass uv:python "project python 3.12" "$v (uv venv)" ;;
  "")     fail uv:python "project python 3.12" "uv could not resolve an interpreter" ;;
  *)      fail uv:python "project python 3.12" "found $v; pyproject requires >=3.12,<3.13" ;;
esac

# Vercel refuses to build with an older uv. The floor is a real blocker, not a preference:
# it stops the local build reproduction that ledger R3 requires.
UV_FLOOR="0.9.25"
if command -v uv >/dev/null 2>&1; then
  uvv=$(uv --version 2>&1 | awk '{print $2}')
  if [ "$(printf '%s\n%s\n' "$UV_FLOOR" "$uvv" | sort -V | head -1)" = "$UV_FLOOR" ]; then
    pass uv:version "uv >= $UV_FLOOR" "$uvv"
  else
    fail uv:version "uv >= $UV_FLOOR" "found $uvv — too old for 'vercel build' locally"
  fi
else
  fail uv:version "uv >= $UV_FLOOR" "not installed"
fi

if command -v docker >/dev/null 2>&1; then
  pass docker:engine "docker" "$(docker --version 2>&1 | awk '{print $3}' | tr -d ,)"
else
  fail docker:engine "docker" "not installed — local database cannot start"
fi

if command -v npx >/dev/null 2>&1; then
  pass vercel:npx "npx (runs vercel cli)" "node $(node --version 2>&1)"
else
  fail vercel:npx "npx (runs vercel cli)" "not installed — vercel cli is not installed globally"
fi

# ------------------------------------------------------------------- 2. database
echo
echo "2. Local database"

if docker compose ps --status running 2>/dev/null | grep -q preempt-db; then
  pgv=$(docker compose exec -T db psql -U preempt -d preempt -tAc 'show server_version' 2>/dev/null | tr -d '[:space:]')
  [ -n "$pgv" ] && pass docker:postgres "postgres reachable (5433)" "server_version $pgv" \
                || fail docker:postgres "postgres reachable (5433)" "container up but psql did not answer"

  ts=$(docker compose exec -T db psql -U preempt -d preempt -tAc \
       "select default_version from pg_available_extensions where name='timescaledb'" 2>/dev/null | tr -d '[:space:]')
  [ -n "$ts" ] && pass docker:timescaledb "timescaledb available" "$ts" \
               || fail docker:timescaledb "timescaledb available" "extension not offered by this image"
else
  fail docker:postgres "postgres reachable (5433)" "container not running — 'docker compose up -d --wait'"
  # Named explicitly rather than left unreported: with the container down this probe cannot
  # run, and an unrun probe must still account for itself or the coverage check is a lie.
  fail docker:timescaledb "timescaledb available" "not checked — container not running"
fi

# The test database is a separate container on a separate port, and until this probe
# existed nothing checked it — while `api/tests/test_reversibility.py` drives it to `base`
# and back on every gate run, and `audit/REVERSIBILITY.txt` makes a version claim about it.
# Two containers from one compose file can still drift: one can be stopped, or left running
# from an older image after the pin changes.
if docker compose ps --status running 2>/dev/null | grep -q preempt-db-test; then
  tpgv=$(docker compose exec -T db-test psql -U preempt -d preempt_test -tAc 'show server_version' 2>/dev/null | tr -d '[:space:]')
  tts=$(docker compose exec -T db-test psql -U preempt -d preempt_test -tAc \
        "select extversion from pg_extension where extname='timescaledb'" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$tpgv" ]; then
    pass docker:postgres-test "test database reachable (5434)" "server_version $tpgv, timescaledb ${tts:-none}"
  else
    fail docker:postgres-test "test database reachable (5434)" "container up but psql did not answer"
  fi
else
  fail docker:postgres-test "test database reachable (5434)" "container not running — migration reversibility is unproven without it"
fi

# The one external data source. Probed because R1 says a service is named and proven before
# code depends on it — and this probe is what found the 429: the endpoint rate-limits after a
# second request in quick succession, which is why `api/tests/test_azure_provider.py` reads
# recorded payloads instead of calling it. One request here, deliberately.
az_body=$(curl -s -m 20 -G \
  --data-urlencode "\$filter=serviceName eq 'Virtual Machines' and armRegionName eq 'eastus'" \
  "https://prices.azure.com/api/retail/prices" 2>/dev/null)
az_count=$(printf '%s' "$az_body" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print(len(d["Items"]) if isinstance(d.get("Items"), list) else "")
except Exception:
    print("")' 2>/dev/null)
if [ -n "$az_count" ] && [ "$az_count" -gt 0 ] 2>/dev/null; then
  pass azure:retail-prices "azure retail prices" "$az_count items for eastus, unauthenticated"
else
  fail azure:retail-prices "azure retail prices" "no Items array — rate limited (429) or shape changed"
fi

# ------------------------------------------------------------------ 3. source host
echo
echo "3. Source host"

if git ls-remote --exit-code origin HEAD >/dev/null 2>&1; then
  pass github:remote "github remote reachable" "$(git config --get remote.origin.url)"
else
  fail github:remote "github remote reachable" "git ls-remote failed"
fi

# ----------------------------------------------------------------------- 4. vercel
echo
echo "4. Vercel"

who=$($VERCEL whoami --scope "$SCOPE" </dev/null 2>/dev/null | tail -1 | tr -d '[:space:]')
if [ -n "$who" ]; then
  pass vercel:auth "vercel cli authenticated" "$who"
else
  fail vercel:auth "vercel cli authenticated" "whoami returned nothing — run 'npx vercel@latest login'"
fi

# Root Directory is a dashboard setting the repository cannot express, which makes it the
# one part of the deployment that can be silently lost. Probe it rather than trust it.
if [ -f .vercel/project.json ]; then
  rd=$(python3 -c "import json;print(json.load(open('.vercel/project.json')).get('settings',{}).get('rootDirectory'))" 2>/dev/null)
  [ "$rd" = "api" ] && pass vercel:rootdir "vercel rootDirectory == api" "$rd" \
                    || fail vercel:rootdir "vercel rootDirectory == api" "found '$rd' — build will produce no function"
else
  fail vercel:rootdir "vercel rootDirectory == api" "not linked — run 'npx vercel@latest pull --yes --environment production'"
fi

envs=$($VERCEL env ls --scope "$SCOPE" </dev/null 2>/dev/null)
case "$envs" in
  *PREEMPT_ENVIRONMENT*) pass vercel:env-environment "env PREEMPT_ENVIRONMENT set" "present (value not printed)" ;;
  *)                     fail vercel:env-environment "env PREEMPT_ENVIRONMENT set" "missing — /health will report 'local' in production" ;;
esac

case "$envs" in
  *PREEMPT_DATABASE_URL*) pass vercel:env-database "env PREEMPT_DATABASE_URL set" "present (value not printed)" ;;
  *) waive vercel:env-database "env PREEMPT_DATABASE_URL set" "not set; no code reads the database before Sprint 1. Waiver lifts when S-004 closes or the first query ships — whichever comes first." ;;
esac

# ------------------------------------------------------------------- 5. deployed
echo
echo "5. Deployed application"

code=$(curl -s -o /dev/null -w '%{http_code}' "$APP/api/v1/health?cb=$(date +%s)" 2>/dev/null)
if [ "$code" = "200" ]; then
  env_reported=$(curl -s "$APP/api/v1/health?cb=$(date +%s)-e" 2>/dev/null \
                 | python3 -c "import json,sys;print(json.load(sys.stdin).get('environment'))" 2>/dev/null)
  if [ "$env_reported" = "production" ]; then
    pass vercel:health "GET /api/v1/health" "HTTP 200, environment=$env_reported"
  else
    fail vercel:health "GET /api/v1/health" "HTTP 200 but environment=$env_reported, not production"
  fi
else
  fail vercel:health "GET /api/v1/health" "HTTP $code"
fi

# The gate is green while every route 404s unless something checks the running system.
# This probe is that check (ledger R2).
body=$(curl -s "$APP/nope-$(date +%s)" 2>/dev/null)
case "$body" in
  *'"detail"'*) pass vercel:routing "unknown route served by app" "FastAPI 404, not a platform 404" ;;
  *)            fail vercel:routing "unknown route served by app" "platform answered — app may not be routing" ;;
esac

# ------------------------------------------------------------------- verdict
echo

# Coverage, not outcome: every probe docs/SERVICES.md declares must have reported
# something above. A probe that exists in this file but never executes is invisible to the
# gate's static check, and this is what sees it.
if ! coverage=$(python3 scripts/check-probes.py --emitted "$SEEN" 2>/dev/null); then
  printf '%s\n' "$coverage" | sed 's/^/  COVERAGE  /'
  fails=$((fails + 1))
  echo
fi

waived="${waived:-0}"
if [ "$waived" -gt 0 ]; then
  printf '  %sWAIVED%s %d of the declared probes, so this run does not prove them:%s\n' \
    "$Y" "$N" "$waived" "${WAIVED_IDS:-}"
fi

if [ "$fails" -eq 0 ]; then
  printf '%sPREFLIGHT: PASS%s (%d waived)\n\n' "$G" "$N" "$waived"
  exit 0
fi
printf '%sPREFLIGHT: FAIL (%d)%s (%d waived)\n\n' "$R" "$fails" "$N" "$waived"
exit 1
