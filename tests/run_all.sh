#!/bin/bash
# Every test in the project. No network, no API spend.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -o pipefail
echo "=== seam 1: hook process boundary ==="
"$ROOT/tests/test_hook.sh" || exit 1
echo
echo "=== seam 2 + 3: pipeline, statistics, report ==="
python3 "$ROOT/tests/test_pipeline.py" 2>&1 | tail -4 || exit 1
echo "=== baseline: known answers from a real transcript ==="
python3 "$ROOT/tests/test_session_metrics.py" 2>&1 | tail -4 || exit 1
echo "=== doctor ==="
python3 "$ROOT/src/doctor.py" | tail -3
