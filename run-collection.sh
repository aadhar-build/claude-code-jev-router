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

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$ROOT/logs/worker.pid"

case "${1:-status}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "already running (pid $(cat "$PIDFILE"))"; exit 0
    fi
    mkdir -p "$ROOT/logs"
    nohup python3 "$ROOT/src/worker.py" --interval 30 \
      >> "$ROOT/logs/worker.log" 2>&1 &
    echo $! > "$PIDFILE"
    echo "worker started (pid $!), polling every 30s"
    echo "  log:    tail -f logs/worker.log"
    echo "  stop:   ./run-collection.sh stop"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null && echo "stopped (pid $(cat "$PIDFILE"))"
      rm -f "$PIDFILE"
    else
      echo "not running"
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "worker: RUNNING (pid $(cat "$PIDFILE"))"
    else
      echo "worker: not running"
    fi
    echo "spool pending : $(ls "$ROOT"/spool/ready/*.json 2>/dev/null | wc -l | tr -d ' ')"
    echo "captures      : $(cat "$ROOT"/data/captures/*.jsonl 2>/dev/null | wc -l | tr -d ' ')"
    echo "runs          : $(cat "$ROOT"/data/runs/*.jsonl 2>/dev/null | wc -l | tr -d ' ')"
    if [ -f "$ROOT/.jev-disabled" ]; then
      echo "capture       : DISABLED (.jev-disabled present)"
    else
      echo "capture       : enabled"
    fi
    ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1 ;;
esac
