#!/bin/bash
# Every test in the project. No network, no API spend.
#
# --------------------------------------------------------------------------
# THIS SUITE RUNS WHILE A COLLECTION WINDOW IS OPEN. IT DOES NOT REFUSE TO.
# --------------------------------------------------------------------------
# JEV-42 asked whether `run_all.sh` should refuse to run while the worker is
# draining, or always sandbox. It always sandboxes, and here is why.
#
# A suite that refuses to run is a suite people stop running. The collection
# window is not a rare event to be waited out -- it is the normal state of this
# repository from go-live until the study ends, and "the full test suite must
# pass" is the instruction in every agent brief. Refusing would mean either
# nobody tests for the duration of the study, or everybody learns the
# environment variable that turns the refusal off, which is the same thing with
# an audit trail that lies. Amendment 6 already shows the failure mode: told
# not to use `run_all.sh`, one agent ran `test_hook.sh` directly.
#
# Refusal would also make correctness depend on `logs/worker.pid`, a file that
# is stale the moment the worker dies unexpectedly. "Is a window open?" is a
# question the suite would get wrong in both directions. "Never touch the live
# tree" is a question it can get right unconditionally.
#
# So: every test runs against a throwaway root, and two guards make that
# enforceable rather than aspirational.
#
#   1. tests/audit_live_writes.sh runs FIRST and the suite does not start if it
#      fails. It enumerates tests/*.sh, so a new test is covered without its
#      author opting in. Static: it catches the mistake before it executes.
#
#   2. tests/lib/live_guard.sh snapshots the live window and re-checks it after
#      EVERY test, naming the test that moved it. Runtime: it catches what the
#      scanner cannot see (Python tests, indirection through variables) after
#      the fact, which is still enormously better than the status quo ante,
#      where the damage was silent and unrecoverable.
#
# The one thing the suite does refuse is to continue after guard 2 fires.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -o pipefail

# JEV-44: the interpreter, before anything else -- before the live-write audit,
# before the first test, before anything that could produce output a reader has
# to interpret.
#
# On an interpreter below 3.12, this suite used to run to completion and report
# 16 errors out of test_pipeline.py, every one of them the same SyntaxError at
# src/arms/jev.py:237 reached through a lazy import in setUp. Sixteen red
# errors that are not about the code under test is how a suite teaches its
# reader to ignore red -- the same failure as JEV-42, one remove further out.
#
# This resolves $JEV_PY to an absolute interpreter, proves it is >= 3.12, and
# prepends its directory to PATH so the shell tests underneath inherit it too.
#
# `exit $?`, not `exit 1`: the guard's 78 (EX_CONFIG) is chosen to be
# distinguishable from a test failure and from src/canary.py's 0-4 verdicts,
# and collapsing it to 1 here would teach the wrong pattern to everything that
# copies this line.
. "$ROOT/tests/lib/require_python.sh" || exit $?

GUARD="$ROOT/tests/lib/live_guard.sh"
SNAP="$(mktemp "${TMPDIR:-/tmp}/jev-live-snapshot.XXXXXX")"
trap 'rm -f "$SNAP"' EXIT

echo "=== JEV-42 guard: no test may write to the live collection window ==="
"$ROOT/tests/audit_live_writes.sh" || {
  echo
  echo "REFUSING TO RUN. A test in this suite writes to the live spool/, data/"
  echo "or logs/. Fix it before running anything -- see ISSUES.md JEV-42."
  exit 1
}
"$GUARD" snapshot "$SNAP"

# Run one test, then prove the live window is where we left it. A test that
# damaged it stops the suite immediately rather than letting the next nine
# tests pile more damage on top.
guarded() { # label, command...
  local label="$1"; shift
  "$@"
  local rc=$?
  "$GUARD" verify "$SNAP" "$label" || exit 1
  return $rc
}

echo
echo "=== seam 1: hook process boundary ==="
guarded "test_hook.sh" "$ROOT/tests/test_hook.sh" || exit 1
echo
echo "=== JEV-42: the sandboxed hook test still catches a broken hook ==="
guarded "test_hook_mutations.sh" "$ROOT/tests/test_hook_mutations.sh" || exit 1
echo
echo "=== seam 1: inline shadow hook (loopback fake, no spend) ==="
guarded "test_inline_shadow.sh" "$ROOT/tests/test_inline_shadow.sh" || exit 1
echo
echo "=== JEV-44: the interpreter floor is asserted, not assumed ==="
guarded "test_python_floor.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_python_floor.py' 2>&1 | tail -4" || exit 1
echo
echo "=== seam 2 + 3: pipeline, statistics, report ==="
guarded "test_pipeline.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_pipeline.py' 2>&1 | tail -4" || exit 1
echo
echo "=== JEV-32: analysis joins rows to the config THEY ran under, and never pools ==="
guarded "test_analyze_config_join.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_analyze_config_join.py' 2>&1 | tail -4" || exit 1
echo
echo "=== JEV-51 + JEV-31: kill switch, graceful stop, and the claim reap ==="
guarded "test_worker_lifecycle.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_worker_lifecycle.py' 2>&1 | tail -4" || exit 1
echo "=== JEV-51: run-collection.sh stop waits, and status separates the two facts ==="
guarded "test_collection_control.sh" bash -c "set -o pipefail; '$ROOT/tests/test_collection_control.sh' | tail -3" || exit 1
echo
echo "=== seam 3b: threshold validation and determinism ==="
guarded "test_validation.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_validation.py' 2>&1 | tail -4" || exit 1
echo "=== JEV-16: sweep selection, and the two things a repeat group must not pool ==="
guarded "test_jev16.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_jev16.py' 2>&1 | tail -4" || exit 1
echo "=== baseline: known answers from a real transcript ==="
guarded "test_session_metrics.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_session_metrics.py' 2>&1 | tail -4" || exit 1

echo "=== baseline: the persisted 'before' record is append-only and idempotent ==="
guarded "test_baseline.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_baseline.py' 2>&1 | tail -4" || exit 1

echo "--- canary: frozen set stability, drift flags, row-schema identity ---"
guarded "test_canary.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/tests/test_canary.py' 2>&1 | tail -4" || exit 1
echo
echo "=== JEV-40: reversibility -- one switch, and OFF proven equal to vanilla ==="
guarded "reversibility.sh" bash -c "set -o pipefail; '$ROOT/tests/reversibility.sh' | tail -4" || exit 1
echo "=== doctor ==="
guarded "doctor.py" bash -c "set -o pipefail; \"$JEV_PY\" '$ROOT/src/doctor.py' | tail -3"

echo
echo "=== live window untouched by the full suite ==="
"$GUARD" verify "$SNAP" "run_all.sh (whole suite)" && \
  echo "  ok    spool, data/ and logs/ are as the suite found them"
