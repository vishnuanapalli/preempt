#!/usr/bin/env bash
#
# Mutation check for the migration-reversibility harness.
#
# `api/tests/test_reversibility.py` claims that it would notice an irreversible
# migration. This script is what makes that claim checkable: it breaks one part of
# `api/tests/reversibility.py` at a time and confirms the suite turns red — for the right
# reason, by node id, not merely with a non-zero exit code. The last case must stay green.
#
# Deliberately NOT part of `scripts/verify.sh`. It edits a tracked file in place, and a
# gate that mutates the working tree is a gate people learn to run only when the tree is
# clean — which is never. The three sabotage shapes that DO run on every gate invocation
# live inside the pytest module itself; this is the layer above, run by hand when the
# harness changes, with its output recorded in `audit/REVERSIBILITY.txt`.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../api" || exit 2

H=tests/reversibility.py
BK="$(mktemp -t reversibility)"
cp "$H" "$BK"
restore() { cp "$BK" "$H"; }
trap 'restore; rm -f "$BK"' EXIT

FAILED=0

# Without a database every integration case skips, so four of these mutations would report
# GREEN and the matrix would print holes that do not exist. Establishing this up front is
# the difference between "the harness is sound" and "nothing ran".
if uv run pytest tests/test_reversibility.py -q 2>/dev/null | grep -q "skipped"; then
  echo "REFUSING TO RUN: some integration tests are skipping, so most cases below would"
  echo "report GREEN for the wrong reason. Start the databases: docker compose up -d --wait"
  exit 2
fi

# name, expected verdict, node id that must be among the failures (empty for GREEN cases),
# python mutation.
run_case() {
  local name="$1" expect="$2" node="$3" py="$4"
  restore
  # A mutation that matches nothing is a case that tested nothing. The first version of
  # this script had one — its pattern hit an identically-worded line in another function
  # — and it reported a hole in the suite that did not exist.
  python3 - "$H" <<PY || { echo "  BROKEN $name -> mutation did not apply"; FAILED=1; return; }
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
before = s
$py
assert s != before, "mutation matched nothing"
p.write_text(s)
PY

  local out
  out="$(uv run pytest tests/test_reversibility.py -q --tb=no 2>&1)"
  local got=GREEN
  grep -qE '^(FAILED|ERROR) ' <<<"$out" && got=RED

  if [ "$got" != "$expect" ]; then
    echo "  BROKEN $name -> $got (expected $expect)"
    FAILED=1
    return
  fi
  # Red is not enough. A mutation that breaks the module import turns everything red and
  # would pass a check that only reads the exit code, while proving nothing about the
  # assertion the case is supposed to be exercising.
  if [ "$expect" = RED ] && ! grep -qE "^(FAILED|ERROR) tests/test_reversibility.py::$node" <<<"$out"; then
    echo "  BROKEN $name -> red, but $node was not among the failures:"
    grep -E '^(FAILED|ERROR) ' <<<"$out" | sed 's/^/           /'
    FAILED=1
    return
  fi
  echo "  ok     $name -> $got${node:+ (via $node)}"
}

echo "sabotage matrix — the harness must go red for the right reason, or stay green"

run_case "diff() always reports no difference" RED \
  "test_a_table_left_behind_is_reported" \
  's = s.replace("    out: list[str] = []", "    out: list[str] = []\n    return out", 1)'

run_case "diff ignores changed definitions" RED \
  "test_a_column_restored_with_a_different_shape_is_reported" \
  's = s.replace("        if b[cls, ident] != a[cls, ident]", "        if False", 1)'

run_case "_attempt() swallows every migration failure" RED \
  "test_the_harness_reports_an_irreversible_migration" \
  's = s.replace("""    try:
        run()
    except Exception as exc:
        return f\"{type(exc).__name__}: {exc}\"""", """    try:
        run()
    except Exception:
        return None""", 1)'

run_case "reversible always True" RED \
  "test_a_round_trip_that_did_not_restore_the_schema_is_not_reversible" \
  's = s.replace("        return not self.all_differences", "        return True", 1)'

run_case "per-migration stepping removed" RED \
  "test_the_harness_stepped_every_migration" \
  's = s.replace("    for index, revision in enumerate(chain):", "    for index, revision in enumerate([]):", 1)'

run_case "step failures excluded from the verdict" RED \
  "test_a_failing_step_makes_the_whole_round_trip_not_reversible" \
  's = s.replace("            self.step_reverse_differences\n            + self.step_reapply_differences\n", "", 1)'

run_case "re-application step removed" RED \
  "test_the_harness_reports_an_irreversible_migration" \
  's = s.replace("    reapply_error = _attempt(lambda: command.upgrade(cfg, revision))", "    reapply_error = None", 1)'

run_case "reverse step removed" RED \
  "test_the_harness_reports_an_irreversible_migration" \
  's = s.replace("    reverse_error = _attempt(lambda: command.downgrade(cfg, previous or \"base\"))", "    reverse_error = None", 1)'

run_case "snapshot() returns nothing" RED \
  "test_the_snapshot_sees_every_class_it_claims_to" \
  's = s.replace("        return Snapshot(objects=tuple(sorted(rows)))", "        return Snapshot(objects=())", 1)'

run_case "covered always reports one object" RED \
  "test_coverage_is_zero_when_the_migrations_create_nothing" \
  's = s.replace("        return len(h - b)", "        return 1", 1)'

run_case "reverse_error not surfaced as a difference" RED \
  "test_a_downgrade_that_raises_is_not_reversible" \
  's = s.replace("            return [f\"downgrading to base failed: {self.reverse_error}\"]", "            return []", 1)'

run_case "reapply_error not surfaced as a difference" RED \
  "test_a_re_application_that_fails_is_not_reversible" \
  's = s.replace("            return [f\"upgrading to head a second time failed: {self.reapply_error}\"]", "            return []", 1)'

# The off switch. A `reachable` that always reports "down" removes every database-backed
# test in the module and leaves ./scripts/verify.sh green, so nothing else in this matrix
# would catch it.
run_case "reachable() always reports the database is down" RED \
  "test_the_skip_decision_matches_reality" \
  's = s.replace("    try:\n        asyncio.run(_ping())", "    if True:\n        return \"OSError: pretend it is down\"\n    try:\n        asyncio.run(_ping())", 1)'

# Six of the object classes were exercised by nothing until the class-coverage test
# existed: cutting _QUERIES to relations and columns produced byte-identical output.
run_case "half the object classes deleted from the snapshot" RED \
  "test_the_snapshot_declares_every_class_this_suite_pins" \
  's = s.replace("OBJECT_CLASSES: tuple[str, ...] = tuple(cls for cls, _ in _QUERIES)", "_QUERIES = tuple(q for q in _QUERIES if q[0] in (\"relation\", \"column\"))\nOBJECT_CLASSES: tuple[str, ...] = tuple(cls for cls, _ in _QUERIES)", 1)'

# Two cases, because the guard and the symptom are different things. With the guard in
# place a NULL component must raise; with the guard removed the collapsed definitions must
# still be caught, or the guard is the only thing standing between a silent snapshot and a
# green suite.
run_case "a NULL component in a definition (guard must raise)" RED \
  "test_the_snapshot_sees_every_class_it_claims_to" \
  's = s.replace("               \x27kind=\x27 || c.relkind::text\n               || \x27 persistence=\x27", "               NULL || c.relkind::text\n               || \x27 persistence=\x27", 1)'

run_case "NULL definitions accepted instead of raising" RED \
  "test_the_snapshot_sees_every_class_it_claims_to" \
  's = s.replace("                    if identity is None or definition is None:", "                    if False:", 1)
s = s.replace("               \x27kind=\x27 || c.relkind::text\n               || \x27 persistence=\x27", "               NULL || c.relkind::text\n               || \x27 persistence=\x27", 1)'

# `public`, timescaledb and a timescaledb catalog trigger keep three classes non-empty in a
# bare database, so a filter that excludes user-schema objects leaves the class present and
# the class check satisfied. This mutation is invisible to it and must be caught by the
# binding to the fixture's own identities.
run_case "the schema query only ever sees public" RED \
  "test_the_snapshot_sees_every_class_it_claims_to" \
  's = s.replace("        SELECT n.nspname, \x27\x27\n        FROM pg_namespace n\n        WHERE n.nspname <> \x27information_schema\x27", "        SELECT n.nspname, \x27\x27\n        FROM pg_namespace n\n        WHERE n.nspname = \x27public\x27", 1)'

run_case "same_database() calls every URL distinct" RED \
  "test_the_same_database_spelled_two_ways_is_detected" \
  's = s.replace("    left, right = make_url(a), make_url(b)", "    return False\n    left, right = make_url(a), make_url(b)", 1)'

run_case "comment-only edit (must stay green)" GREEN "" \
  's = s.replace("# One row per schema object", "# one row per schema object", 1)'

restore
# The harness must be byte-identical to what it was before this script ran. Without this
# the script can leave a mutation behind and the next gate run reports someone else's bug.
if ! cmp -s "$H" "$BK"; then
  echo "  BROKEN $H was not restored"
  FAILED=1
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "SABOTAGE: every case behaved as expected"
else
  echo "SABOTAGE: FAILED"
fi
exit "$FAILED"
