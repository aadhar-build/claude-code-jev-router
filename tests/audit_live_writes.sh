#!/bin/bash
# JEV-42: the static half of the guard. Runs FIRST in run_all.sh, before any
# test executes, and refuses to let the suite start if any shell test still
# writes to the live collection window.
#
# WHY A DIRECTORY SCAN RATHER THAN A HELPER EACH TEST CALLS
# --------------------------------------------------------
# A `assert_sandboxed` helper only protects the tests that remember to call it,
# and the test that destroyed 14:10Z-15:05Z was written before the spool was
# live -- it would not have called anything. This scanner ENUMERATES
# tests/*.sh instead, so a new test is covered the moment it lands, without its
# author having opted in. That is the only property that makes it a guard
# rather than a convention.
#
# WHAT COUNTS AS A VIOLATION
#   1. a destructive verb (rm / mv / cp / chmod / chown / ln / truncate) or an
#      output redirect, aimed at $ROOT/spool, $ROOT/data, $ROOT/logs or
#      $ROOT/.jev-disabled
#   2. CLAUDE_PROJECT_DIR set to $ROOT -- that is what points a live hook at
#      the real spool, and it is how a capture lands there even with no rm in
#      sight
#
# `mkdir` and `mktemp` are deliberately NOT destructive verbs: creating a fresh
# throwaway directory under the gitignored logs/ is exactly the sanctioned
# sandbox pattern (gates.sh does it), and flagging it would train people to add
# exemptions.
#
# READ-ONLY references are fine and must stay fine: gates.sh greps the live
# spool to assert it left no trace there, which is the opposite of the defect.
# So the rule is verb-based, not path-based.
#
# ESCAPE HATCH: a line ending `# jev-live-ok: <reason>` is exempt and is
# printed in the report, so exemptions are visible rather than silent.
#
# LIMIT, STATED PLAINLY: this scans shell. The Python tests redirect
# `paths.*` at a tempdir in setUp (test_pipeline.TempStorage,
# test_canary, test_baseline, test_validation) and are safe by CONVENTION, not
# by enforcement -- a new Python test that forgets is caught only by the
# runtime tripwire in tests/lib/live_guard.sh, not here.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Optional argument: a directory of shell tests to scan instead of tests/.
# tests/test_hook_mutations.sh uses it to point the scanner at the PRE-FIX
# test_hook.sh recovered from git, which is the scanner's own mutation test --
# a checker that has never been shown catching the bug it was written for is
# not evidence of anything.
SCAN="${1:-$ROOT/tests}"

python3 - "$SCAN" <<'PY'
import os, re, sys

tests = sys.argv[1]

LIVE = re.compile(r'\$\{?ROOT\}?"?/(spool|data|logs)\b|\$\{?ROOT\}?"?/\.jev-disabled')
VERB = re.compile(r'(?:^|[\s;&|(])(rm|mv|cp|chmod|chown|ln|truncate)\s')
REDIR = re.compile(r'(?<![0-9<>])>>?\s*"?\$\{?ROOT')
CPD = re.compile(r'CLAUDE_PROJECT_DIR=\{?"?\$\{?ROOT\}?')
EXEMPT = re.compile(r'#\s*jev-live-ok:')

violations, exemptions = [], []
scanned = []

for name in sorted(os.listdir(tests)):
    if not name.endswith(".sh"):
        continue
    # The scanner is not a test, and its own patterns are written out in full
    # in its source, so scanning itself reports itself.
    if name == "audit_live_writes.sh":
        continue
    path = os.path.join(tests, name)
    scanned.append(name)
    for n, raw in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        line = raw.rstrip("\n")
        if line.lstrip().startswith("#"):
            continue
        why = None
        if CPD.search(line):
            why = "points a hook at the LIVE project root (CLAUDE_PROJECT_DIR=$ROOT)"
        elif LIVE.search(line) and (VERB.search(line) or REDIR.search(line)):
            why = "destructive write to the live spool/ data/ logs/ or kill switch"
        if why is None:
            continue
        if EXEMPT.search(line):
            exemptions.append((name, n, line.strip()))
        else:
            violations.append((name, n, why, line.strip()))

print("audit: live-window writes in shell tests")
print("  scanned: " + ", ".join(scanned))
for name, n, line in exemptions:
    print(f"  exempt  {name}:{n}  {line[:100]}")
if not violations:
    print(f"  ok    no shell test writes to the live spool/, data/, logs/ or kill switch")
    print(f"  -> {len(scanned)} files clean, {len(exemptions)} declared exemption(s)")
    sys.exit(0)

for name, n, why, line in violations:
    print(f"  FAIL  {name}:{n}  {why}")
    print(f"           {line[:120]}")
print()
print("  A test must never write to the real spool/, data/ or logs/. A live")
print("  worker drains spool/ready; a capture deleted there leaves no capture")
print("  row and no run row, so the loss cannot even be counted as attrition.")
print("  See PREREGISTRATION.md Amendment 6 and ISSUES.md JEV-42.")
print("  Point CLAUDE_PROJECT_DIR at a throwaway root: tests/gates.sh and")
print("  tests/test_hook.sh are the reference implementations.")
sys.exit(1)
PY
