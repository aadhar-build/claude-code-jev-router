#!/bin/bash
# Drain the capture spool continuously for the collection window.
#
# The plan called for the worker to run in a visible terminal, on the principle
# that "the experiment is running" should be an observable state. For an
# unattended multi-day window that is impractical, so this is the compromise:
# started deliberately, never self-starting, logging where you can see it, and
# stopped with a single obvious command.
#
#   ./run-collection.sh start   # begin draining
#   ./run-collection.sh status  # what has accumulated
#   ./run-collection.sh stop    # stop draining (capture continues)
#
# Note the asymmetry: stopping the worker does NOT stop capture. The hook keeps
# spooling, and a captured state is permanently replayable, so nothing is lost
# by draining later. To stop CAPTURE, touch .jev-disabled.
#
# THE OTHER HALF OF THAT ASYMMETRY, AND WHY IT IS A DEFECT WORTH NAMING (JEV-51)
# -----------------------------------------------------------------------------
# `.jev-disabled` used to stop capture and NOT the worker, so a spool that was
# already full kept being drained against every enabled arm. "Disabled" meant
# "stops recording new decisions", not "stops spending money", while `status`
# printed `capture: DISABLED` and said nothing about a worker that was still
# making API calls. The worker now honours the switch (worker.py, drain_once),
# and `status` below reports the two as SEPARATE FACTS, because they are:
#
#   capture disabled   the hook writes no new spool files
#   worker quiescent   no arm is being called for the files already there
#
# Either can be true without the other. The fully-off state is both, and
# `docs/REVERSIBILITY.md` gives the one-command path to it.

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$ROOT/logs/worker.pid"

# JEV-44. Resolve the interpreter ONCE, by absolute path, and refuse below the
# floor. This matters more here than anywhere else in the repo: `start`
# DAEMONISES, so a bare `python3` would bind whatever the invoker's PATH
# happened to resolve to for the entire multi-day window -- either a long-lived
# process on an unintended runtime, or a SyntaxError into logs/worker.log that
# nobody reads until captures stop arriving.
#
# This uses the two-liner against src/pyversion.py rather than sourcing
# tests/lib/require_python.sh, deliberately. run-collection.sh is a PRODUCTION
# entry point: making it depend on the test tree means it cannot be copied,
# packaged or vendored without tests/, and `tests/test_collection_control.sh`
# demonstrated exactly that by failing the moment the dependency was added.
# The library remains the right choice for scripts that already live under
# tests/. `|| exit $?` and not `|| exit 1`: the guard's 78 (EX_CONFIG) is
# chosen to be distinguishable from a real failure, and collapsing it loses
# that. $JEV_PYTHON is the override and is honoured strictly.
JEV_PY="${JEV_PYTHON:-/opt/homebrew/bin/python3}"
[ -x "$JEV_PY" ] || JEV_PY="$(command -v python3)"
"$JEV_PY" "$ROOT/src/pyversion.py" || exit $?

# How long `stop` waits for a graceful exit. The worker finishes the capture it
# is dispatching before it exits, and a dispatch is bounded by the slowest
# enabled arm's timeout_s: 180s for the cc_* arms, 240s for cc_fable51. 300s
# covers the worst case with headroom. Overridable for tests only.
STOP_TIMEOUT="${JEV_STOP_TIMEOUT:-300}"

# ANY entry at the path means OFF -- a regular file, a directory, an unreadable
# file or a dangling symlink (JEV-40). The same test every hook performs.
switch_on() { [ -e "$ROOT/.jev-disabled" ] || [ -L "$ROOT/.jev-disabled" ]; }

claimed_count() { ls "$ROOT"/spool/claimed/*.json 2>/dev/null | wc -l | tr -d ' '; }

case "${1:-status}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "already running (pid $(cat "$PIDFILE"))"; exit 0
    fi
    mkdir -p "$ROOT/logs"
    # -u: unbuffered. Without it Python block-buffers stdout under nohup and
    # an operator tailing worker.log sees nothing for hours (JEV-33).
    nohup "$JEV_PY" -u "$ROOT/src/worker.py" --interval 30 \
      >> "$ROOT/logs/worker.log" 2>&1 &
    echo $! > "$PIDFILE"
    echo "worker started (pid $!), polling every 30s"
    echo "  log:    tail -f logs/worker.log"
    echo "  stop:   ./run-collection.sh stop"
    ;;
  stop)
    # SIGTERM used to land on Python's DEFAULT disposition, which terminates
    # the process instantly -- possibly mid-dispatch, leaving a file in
    # spool/claimed/ that nothing ever moved back. That is the unnamed cause of
    # JEV-31's stranded claims, and it is why this command now waits and then
    # CHECKS rather than printing "stopped" and walking away.
    if [ ! -f "$PIDFILE" ]; then
      echo "not running"
      exit 0
    fi
    pid="$(cat "$PIDFILE")"
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "not running (stale pidfile for pid $pid); removing it"
      rm -f "$PIDFILE"
      exit 0
    fi

    echo "stopping worker (pid $pid): SIGTERM, then waiting for a graceful exit."
    echo "  The worker finishes the capture it is dispatching before it exits, so"
    echo "  this can take up to one dispatch -- bounded by the slowest enabled arm's"
    echo "  timeout_s (180s for the cc_* arms, 240s for cc_fable51). It is not hung."
    echo "  Waiting up to ${STOP_TIMEOUT}s."
    kill -TERM "$pid" 2>/dev/null

    waited=0
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$STOP_TIMEOUT" ]; do
      sleep 1
      waited=$((waited + 1))
      if [ $((waited % 15)) -eq 0 ]; then
        echo "  still finishing the in-flight capture... ${waited}s"
      fi
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "worker (pid $pid) did NOT exit within ${STOP_TIMEOUT}s -- it is STILL RUNNING."
      echo "  The pidfile is left in place deliberately. Escalating to SIGKILL will"
      echo "  strand whatever is in spool/claimed/, which the next start reaps."
      echo "  Escalate on purpose:  kill -9 $pid"
      exit 1
    fi
    rm -f "$PIDFILE"
    echo "stopped (pid $pid) after ${waited}s"

    n_claimed="$(claimed_count)"
    if [ "$n_claimed" -gt 0 ]; then
      echo "WARNING: spool/claimed/ is NOT empty -- $n_claimed capture(s) stranded by this stop."
      echo "  They are undrained work with no run row, so they are attrition that the"
      echo "  attrition count cannot see (JEV-31). The next \`start\` reaps them back"
      echo "  into spool/ready/ automatically; do not delete them."
      exit 1
    fi
    echo "spool claimed : 0   (nothing was stranded by this stop)"
    ;;
  status)
    # The worker's state and the capture hook's state are two separate facts
    # and are printed as two separate lines. Conflating them told an operator
    # "capture: DISABLED" while four arms were still being called (JEV-51).
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      if switch_on; then
        echo "worker        : RUNNING (pid $(cat "$PIDFILE")) but QUIESCENT"
        echo "                the kill switch is present, so it claims nothing and calls no arms"
      else
        echo "worker        : RUNNING (pid $(cat "$PIDFILE")), draining"
      fi
    else
      echo "worker        : not running"
    fi
    # Spool depth, its high-water mark for the window, and the count of
    # captures dropped on backpressure -- so a backlog is visible while it is
    # forming rather than after it has hit the cap (JEV-33). Sampling here
    # means an operator running `status` also advances the mark.
    "$JEV_PY" "$ROOT/src/spool_watch.py" --sample 2>/dev/null \
      || echo "spool ready   : $(ls "$ROOT"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' ')"
    # JEV-30. The identity of the config on disk RIGHT NOW, derived from the
    # bytes. A running worker pinned its own copy at startup and prints it in
    # logs/worker.log; if the two disagree, the worker is running on config
    # that no longer exists on disk and needs a restart.
    echo "config        : $("$JEV_PY" -c "import sys; sys.path.insert(0, '$ROOT/src'); import config_loader as cl; print(cl.config_fingerprint()['config_sha256'])" 2>/dev/null || echo "unreadable")"
    echo "captures      : $(cat "$ROOT"/data/captures/*.jsonl 2>/dev/null | wc -l | tr -d ' ')"
    echo "runs          : $(cat "$ROOT"/data/runs/*.jsonl 2>/dev/null | wc -l | tr -d ' ')"
    # Same fail-safe test the hooks use (JEV-40): ANY entry at the path means
    # OFF. `[ -f ]` here would print "enabled" after someone ran
    # `mkdir .jev-disabled`, i.e. tell the operator the exact opposite of what
    # every hook is doing.
    if switch_on; then
      echo "capture       : DISABLED (.jev-disabled present)"
    else
      echo "capture       : enabled"
    fi
    ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1 ;;
esac
