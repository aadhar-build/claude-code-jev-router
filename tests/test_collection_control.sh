#!/bin/bash
# JEV-51: `run-collection.sh stop` must be graceful, and `status` must report
# the worker and the capture hook as TWO SEPARATE FACTS.
#
# Today `stop` sends a bare SIGTERM and returns immediately, so it reports
# "stopped" while the process is still dispatching, and it never looks at
# `spool/claimed/`. And `status` prints `capture: DISABLED` while the worker is
# still calling four arms -- an operator reading it concludes the experiment is
# spending nothing, which is the exact opposite of the truth.
#
# SANDBOXING. Everything below runs against a COPY of run-collection.sh in a
# mktemp directory, with a fake `src/worker.py` that does nothing but sleep.
# The script derives its own ROOT from `dirname $0`, so the copy is anchored on
# the sandbox and cannot see the live spool, data or logs. The sandbox variable
# is deliberately NOT named ROOT: tests/audit_live_writes.sh keys on the
# literal `$ROOT/spool|data|logs`, and shadowing that name inside a test is how
# a real violation would be hidden from the scanner.

SBX="$(mktemp -d "${TMPDIR:-/tmp}/jev-control.XXXXXX")"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
trap 'rm -rf "$SBX"' EXIT

fails=0
ok()   { echo "  ok    $1"; }
bad()  { echo "  FAIL  $1"; fails=$((fails + 1)); }
has()  { case "$2" in *"$1"*) return 0 ;; *) return 1 ;; esac }

mkdir -p "$SBX/src" "$SBX/logs" "$SBX/spool/ready" "$SBX/spool/claimed" "$SBX/data"
cp "$SRC/run-collection.sh" "$SBX/run-collection.sh"
chmod +x "$SBX/run-collection.sh"
# JEV-44: the script preflights the interpreter against src/pyversion.py before
# doing anything. The sandbox mirrors the real layout rather than the script
# being made tolerant of its absence -- a preflight that silently skips when its
# guard is missing is not a preflight.
cp "$SRC/src/pyversion.py" "$SBX/src/pyversion.py"

# A stand-in worker. It installs the SAME graceful contract the real worker
# does -- SIGTERM sets a flag, the "in-flight capture" finishes, exit 0 -- so
# this test is about the SHELL's half of the handshake, not Python's. The
# worker's own half is asserted in tests/test_worker_lifecycle.py against the
# real worker.main() in a real process.
cat > "$SBX/src/worker.py" <<'PY'
import signal, sys, time
_stop = False
def handler(signum, frame):
    global _stop
    _stop = True
def main():
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    while not _stop:
        time.sleep(0.1)
    # The honest cost of graceful: finishing what was in flight takes time.
    # 2s stands in for a dispatch; the real bound is the slowest arm's
    # timeout_s, which is what `stop` prints and what STOP_TIMEOUT covers.
    time.sleep(2.0)
    return 0
raise SystemExit(main())
PY

echo "=== 1. status reports the worker and the capture hook separately ==="

out="$("$SBX/run-collection.sh" status 2>&1)"
worker_lines="$(printf '%s\n' "$out" | grep -c '^worker ')"
capture_lines="$(printf '%s\n' "$out" | grep -c '^capture ')"
if [ "$worker_lines" -ge 1 ] && [ "$capture_lines" -ge 1 ]; then
  ok "status prints a worker line and a capture line"
else
  bad "status must print both a worker: and a capture: line (got $out)"
fi

# The defect in one assertion: switch present, worker running, and today the
# operator is told only "capture: DISABLED".
: > "$SBX/.jev-disabled"
"$SBX/run-collection.sh" start >/dev/null 2>&1
sleep 0.5
out="$("$SBX/run-collection.sh" status 2>&1)"
if has "DISABLED" "$out"; then
  ok "status reports capture DISABLED when the switch is present"
else
  bad "status did not report the capture state"
fi
wline="$(printf '%s\n' "$out" | grep '^worker ')"
if has "QUIESCENT" "$wline"; then
  ok "status distinguishes a RUNNING-but-quiescent worker from a draining one"
else
  bad "a running worker under the kill switch must not read as draining: $wline"
fi

rm -f "$SBX/.jev-disabled"
out="$("$SBX/run-collection.sh" status 2>&1)"
wline="$(printf '%s\n' "$out" | grep '^worker ')"
if has "draining" "$wline" && ! has "QUIESCENT" "$wline"; then
  ok "with the switch absent the same worker reads as draining"
else
  bad "the quiescent/draining distinction is not driven by the switch: $wline"
fi

echo "=== 2. stop waits for the worker to finish, and says why it waits ==="

start="$(date +%s)"
out="$(JEV_STOP_TIMEOUT=30 "$SBX/run-collection.sh" stop 2>&1)"
rc=$?
elapsed=$(( $(date +%s) - start ))

if [ "$rc" -eq 0 ]; then ok "stop exits 0 on a clean stop"; else bad "stop rc=$rc: $out"; fi
if [ "$elapsed" -ge 2 ]; then
  ok "stop waited for the process to exit (${elapsed}s)"
else
  bad "stop returned in ${elapsed}s -- it did not wait for the worker"
fi
if has "180" "$out" || has "timeout" "$out" || has "dispatch" "$out"; then
  ok "stop explains the wait rather than appearing hung"
else
  bad "stop must say why it is waiting: $out"
fi
if [ ! -f "$SBX/logs/worker.pid" ]; then
  ok "the pidfile is removed only after the process is gone"
else
  bad "pidfile survived a successful stop"
fi
if has "claimed" "$out"; then
  ok "stop reports on spool/claimed/"
else
  bad "stop must verify spool/claimed/ is empty: $out"
fi

echo "=== 3. stop reports a stranded claim instead of swallowing it ==="

"$SBX/run-collection.sh" start >/dev/null 2>&1
sleep 0.3
: > "$SBX/spool/claimed/pre_bash__1-1__p999999__t1__r0.json"
out="$(JEV_STOP_TIMEOUT=30 "$SBX/run-collection.sh" stop 2>&1)"
rc=$?
rm -f "$SBX/spool/claimed/"*.json
if [ "$rc" -ne 0 ]; then
  ok "a stop that leaves a stranded claim does not exit 0"
else
  bad "stop exited 0 with a file stranded in claimed/"
fi
if has "1 capture(s) stranded" "$out" && has "WARNING" "$out"; then
  ok "the stranded claim is named in the output"
else
  bad "stop said nothing about the stranded claim: $out"
fi

echo "=== 4. stop on a worker that is not running is not an error ==="
out="$("$SBX/run-collection.sh" stop 2>&1)"
if [ $? -eq 0 ] && has "not running" "$out"; then
  ok "stop is idempotent"
else
  bad "stop on a dead worker: $out"
fi

echo
if [ "$fails" -eq 0 ]; then
  echo "run-collection control: all checks passed"
  exit 0
fi
echo "run-collection control: $fails check(s) failed"
exit 1
