#!/bin/bash
# JEV-42: proof that tests/test_hook.sh still catches real defects after being
# moved into a sandbox.
#
# The obvious failure mode of "stop the test touching anything real" is a test
# that no longer touches anything AT ALL and passes for that reason. A green
# suite that cannot go red is worse than the bug it replaced, so this file does
# to test_hook.sh what GATE 4 does to the state builder (JEV-15): it breaks the
# subject on purpose, one guard at a time, and requires the specific assertion
# that is supposed to notice to be the one that fails.
#
# hooks/capture.sh is NEVER edited. A live session is firing it right now.
# Every mutant is a COPY inside a throwaway sandbox, handed to test_hook.sh
# through JEV_TEST_HOOK.
#
# The second half does the same for tests/audit_live_writes.sh, against the
# genuine article: the pre-fix test_hook.sh recovered from git. A scanner that
# has never been shown catching the bug it was written for is not evidence.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/logs"
SANDBOX="$(mktemp -d "$ROOT/logs/mutants.XXXXXX")" || exit 1
cleanup() { chmod -R u+rwX "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

SRC="$ROOT/hooks/capture.sh"
OUT="$SANDBOX/run.out"
pass=0; fail=0
ok()  { echo "  ok    $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }

echo "JEV-42: mutation proof -- the sandboxed test must still go red"

# --- control ----------------------------------------------------------------
# An unmutated copy, run through exactly the same JEV_TEST_HOOK path as every
# mutant. If this is not green the mutants below prove nothing.
cp "$SRC" "$SANDBOX/control.sh"; chmod +x "$SANDBOX/control.sh"
if JEV_TEST_HOOK="$SANDBOX/control.sh" "$ROOT/tests/test_hook.sh" >"$OUT" 2>&1; then
  ok "control: an unmutated copy passes ($(grep -c '^  ok' "$OUT") assertions)"
elif [ "$(grep -c '^  FAIL' "$OUT")" = "1" ] && grep -q '^  FAIL  too slow' "$OUT"; then
  # The latency budget is the one assertion in test_hook.sh that measures the
  # machine rather than the hook, and this driver deliberately loads the
  # machine by running the hook some three hundred times. A control that is
  # green except for the clock still establishes what the control is for: that
  # every CORRECTNESS assertion passes on an unmutated hook.
  ok "control: every correctness assertion passes ($(grep '^  FAIL' "$OUT" | tr -d '\n') under this driver's own load)"
else
  bad "control: the unmutated copy FAILED -- $(grep '^  FAIL' "$OUT" | head -3)"
fi

# --- the mutants ------------------------------------------------------------
# mutate <label> <sed program> <expected FAIL substring>
mutate() {
  local label="$1" prog="$2" want="$3" mutant
  mutant="$SANDBOX/m.sh"
  sed "$prog" "$SRC" > "$mutant"; chmod +x "$mutant"
  if cmp -s "$SRC" "$mutant"; then
    bad "$label: the mutation did not change the hook (sed program is stale)"
    return
  fi
  JEV_TEST_HOOK="$mutant" "$ROOT/tests/test_hook.sh" >"$OUT" 2>&1
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    bad "$label: the broken hook PASSED -- that assertion is vacuous"
  elif grep -q "FAIL  $want" "$OUT"; then
    ok "$label -> caught by: $want"
  else
    bad "$label: failed, but not on '$want' (got: $(grep '^  FAIL' "$OUT" | head -2 | tr '\n' ';'))"
  fi
}

mutate "kill switch removed" \
  '/jev-disabled" \]; } && exit 0/d' \
  "captured despite kill switch"

mutate "cwd guard removed" \
  '/^case "\$PWD\/" in/,/^esac/d' \
  "captured from outside cwd"

mutate "recursion guard removed" \
  '/JEV_ARM_SUBPROCESS" \] && exit 0/d' \
  "captured from an arm subprocess"

mutate "empty-record check removed" \
  '/^\[ -s "\$STAGED" \]/d' \
  "spooled an empty record"

mutate "backpressure cap raised to 999999" \
  's/"\$#" -gt 500/"$#" -gt 999999/' \
  "wrote past cap"

mutate "atomic move becomes a copy (staging left dirty)" \
  's/^mv -f "\$STAGED"/cp "$STAGED"/' \
  "staging dir not clean"

# `; echo x` rather than a second line: BSD sed does not expand \n in the
# replacement, and `trap ...; echo x` is the same thing to bash.
mutate "a stray byte on stdout" \
  "s/^trap 'exit 0' EXIT/trap 'exit 0' EXIT; echo x/" \
  "stdout was"

mutate "fail-open broken: the hook exits nonzero" \
  "s/^trap 'exit 0' EXIT/trap 'exit 1' EXIT/" \
  "exit code was 1"

# The one mutant that is DELIBERATELY NOT RUN, and why.
#
# The natural ninth mutation is a hook with `ROOT="$ROOT"` hardcoded instead of
# read from CLAUDE_PROJECT_DIR: it would escape the sandbox and the final
# live-window assertion in test_hook.sh would catch it. That mutation is not
# performed, because performing it means writing ~40 synthetic captures into
# the real spool/ready -- which a running worker would then drain, bill against
# real arms, and write into data/captures and data/runs as if they were real
# decision points. Proving a data-loss guard by contaminating the dataset is
# the JEV-42 mistake with the sign flipped.
#
# What CAN be proved without touching anything live is that the detector
# expression is capable of finding a planted capture at all -- a grep that
# matched nothing because it was malformed would report "no trace" forever.
# So run the identical expression against a decoy tree.
DECOY="$SANDBOX/decoy"
mkdir -p "$DECOY/spool/ready" "$DECOY/data/captures"
printf '{"session_id":"hooktest-99999"}\n' > "$DECOY/spool/ready/pre_bash__x.json"
DETECTED=$( { grep -rl "hooktest-99999" "$DECOY/spool" 2>/dev/null; \
              grep -rl "hooktest-99999" "$DECOY/data/captures" 2>/dev/null; } | wc -l | tr -d ' ')
[ "$DETECTED" = "1" ] \
  && ok "the live-window detector finds a planted capture (expression is not vacuous)" \
  || bad "the live-window detector found nothing in a tree it was given one ($DETECTED)"

# --- the scanner's own mutation test ----------------------------------------
# Recover the pre-fix test_hook.sh -- the file that actually destroyed live
# captures -- and require tests/audit_live_writes.sh to name its destructive
# lines. This is the only check here that runs against the real defect rather
# than a synthetic one.
echo
echo "  --- audit_live_writes.sh against the pre-fix test_hook.sh ---"
# PINNED, not HEAD. Once the fix is committed, HEAD:tests/test_hook.sh is the
# SANDBOXED file, which the scanner passes -- and this proof would invert into
# a permanent false failure. b523902 is the last commit carrying the
# destructive test_hook.sh, and the line numbers below are that file's.
PREFIX_COMMIT="b523902695ac"
OLD="$SANDBOX/old"
mkdir -p "$OLD"
if git -C "$ROOT" show "$PREFIX_COMMIT:tests/test_hook.sh" > "$OLD/test_hook.sh" 2>/dev/null; then
  if "$ROOT/tests/audit_live_writes.sh" "$OLD" >"$OUT" 2>&1; then
    bad "the scanner passed the file that destroyed live captures"
  else
    ok "the scanner REJECTS the pre-fix test_hook.sh"
    for expect in \
      'test_hook.sh:18' 'test_hook.sh:38' 'test_hook.sh:58' 'test_hook.sh:85' \
      'test_hook.sh:121'; do
      grep -q "$expect" "$OUT" && ok "  names $expect" || bad "  did not name $expect"
    done
  fi
else
  # Not a skip. A proof that quietly opts out when its fixture is missing is
  # precisely the failure this file exists to argue against.
  bad "$PREFIX_COMMIT:tests/test_hook.sh could not be read -- the scanner has no mutation test"
fi

# And the negative direction: a read-only reference to the live spool -- which
# is what gates.sh uses to PROVE it left no trace -- must not be flagged, or
# the scanner teaches people to add exemptions.
CLEAN="$SANDBOX/clean"
mkdir -p "$CLEAN"
{
  echo '#!/bin/bash'
  echo 'ROOT="$(cd "$(dirname "$0")/.." && pwd)"'
  echo 'mkdir -p "$ROOT/logs"'
  echo 'SANDBOX="$(mktemp -d "$ROOT/logs/x.XXXXXX")"'
  echo 'LEAKED=$(grep -rl "$SESSION" "$ROOT/spool" 2>/dev/null | wc -l)'
  echo 'rm -rf "$SANDBOX"'
} > "$CLEAN/test_readonly.sh"
if "$ROOT/tests/audit_live_writes.sh" "$CLEAN" >/dev/null 2>&1; then
  ok "the scanner ACCEPTS a read-only grep of the live spool and a logs/ sandbox"
else
  bad "the scanner flags the sanctioned sandbox pattern -- it would train exemptions"
fi

echo
echo "  -> $pass passed, $fail failed"
[ "$fail" -eq 0 ]
