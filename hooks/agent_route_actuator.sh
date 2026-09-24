#!/bin/bash
# jev W1 -- THE STATIC FLOOR. The first actuator in this repo (JEV-35).
#
# A PreToolUse hook on the `Agent` tool that applies a static
# `subagent_type -> tier` map from config/tiers.json by rewriting
# `tool_input.model`. There is no classifier here, no network call, no Jev call,
# no API key, and nothing that can time out. Five independent sources find
# learned routers frequently fail to beat a trivial static rule; this is that
# rule, shipped first, as the baseline anything cleverer has to beat.
#
# WHAT KEEPS THIS INERT -- corrected 2026-09-21, and read this before you
# believe any config file about it.
#
# TWO THINGS, AND ONLY TWO:
#   (a) no entry for this script in the routed project's
#       .claude/settings.local.json -- i.e. `jev install` has not been run, or
#       `jev uninstall` has been; and
#   (b) the kill switches, tested by the two canonical blocks further down --
#       the global one, the per-project one, and the machine-wide one. Their
#       paths are written out THERE and deliberately not repeated here: a
#       second copy of the switch path outside the blocks that own it is the
#       thing that drifts, and tests/reversibility.sh fails the hook for it.
#       (That guard caught this very comment on its first draft.)
#
# `config/surfaces.json` IS NOT ONE OF THEM. THIS SCRIPT NEVER READS THAT FILE.
# `surfaces.agent_route.mode` is not consulted anywhere in the routing path --
# not here, and not in src/install.py, which registers from
# config/registration.json alone. Setting it to "off", to "shadow", or to
# anything else changes NOTHING about whether this hook rewrites
# `tool_input.model`.
#
# THERE IS NO SHADOW MODE FOR THIS ACTUATOR. Registering it IS arming it: once
# the entry exists and no switch is set, it rewrites. The record-only
# `agent_route` surface described by JEV-34 is the capture.sh/spool path -- a
# different script, which does not write data/agent_route/assignments/.
#
# This header used to say "`agent_route` is `mode: off` in config/surfaces.json"
# as though that were a control. It is not one. During the JEV-52 gate run that
# sentence nearly produced a live, model-rewriting hook under the belief that it
# was shadowed. Arming is a deliberate act (JEV-52), performed by registering
# the entry and clearing the switch, and by nothing else.
#
# ---------------------------------------------------------------------------
# FAIL SAFE AND FAIL TO FRONTIER ARE NOT THE SAME THING
# ---------------------------------------------------------------------------
# This repo has already shipped a kill switch that stopped one writer and not
# the other, so the two properties are separated here explicitly.
#
#   FAIL SAFE (absolute, structural).  `trap 'exit 0' EXIT` on the first line
#   makes every unhandled error inert: the hook exits 0, emits nothing, and the
#   tool input is untouched. Nothing this script can do may wedge a session.
#
#   FAIL TO FRONTIER (a routing decision, and only a routing decision).
#   Operator decision 2026-09-21, overriding the default recommendation: when
#   the router cannot decide but a FAITHFUL rewrite is still constructible, the
#   task goes to the frontier tier rather than a cheap one. Quality is protected
#   on the error path; cost is not.
#
# The boundary between them is the payload. Fail-to-frontier requires echoing
# every field of `tool_input` back, so it is reachable ONLY after `tool_input`
# has parsed. Before that -- no jq, empty stdin, garbage stdin -- there is no
# faithful `updatedInput` to build, and the only correct action is to emit
# nothing. Emitting a partial object would spawn the wrong agent type, which is
# indistinguishable in the results from a routing-quality effect. So:
#
#   payload parsed + config broken   -> frontier rewrite, all fields echoed
#   payload unparseable              -> ZERO bytes on stdout, input untouched
#
# Both count as router failures for the breaker. Neither can break the session.
#
# ---------------------------------------------------------------------------
# THE CIRCUIT BREAKER, AND WHY IT IS MANDATORY
# ---------------------------------------------------------------------------
# Fail-to-frontier protects quality and does not protect cost: a sustained
# failure silently bills frontier rates for as long as it lasts. After N
# consecutive failures inside the TTL the hook STOPS REWRITING ENTIRELY, leaves
# the input untouched, drops a sticky marker file, and says so in a
# `systemMessage` -- the loudest channel a hook actually has, since stdout is a
# permission decision and stderr is a log nobody reads.
#
# State is an APPEND-ONLY OUTCOME LOG, never a counter file. Parallel `Agent`
# spawns are the normal case in this harness and a read-modify-write counter
# loses increments under exactly the conditions that matter. One short line per
# outcome, O_APPEND and well under PIPE_BUF, interleaves cleanly -- the property
# hooks/capture.sh already relies on. Open/closed is DERIVED from the tail of
# that log, so there is no stuck state and no reset step to forget, and
# half-open falls out for free: past the TTL the newest failure is stale, one
# attempt is allowed, and its own outcome line decides. While the breaker is
# open nothing is appended, so the TTL can actually expire.
#
# Usage: agent_route_actuator.sh          (PreToolUse/Agent payload on stdin)

# The trap comes FIRST, before anything that can fail -- capture.sh's discipline
# transplanted verbatim, and for the same reason: logs/ is gitignored, so on a
# fresh checkout a failed stderr redirect would exit non-zero before any later
# trap could catch it.
trap 'exit 0' EXIT
# No `set -e`: a failure must skip the decision, not abort with a nonzero status.

# STDOUT DISCIPLINE, MADE STRUCTURAL RATHER THAN REMEMBERED.
# Claude Code parses this hook's stdout as a permission decision, so a stray
# byte from jq, tail or openssl would be us gating a tool call we promised never
# to gate. inline_shadow_bash.sh closes stdout outright; this hook cannot,
# because emitting on stdout is its whole job. So instead: fd 3 becomes the real
# stdout and fd 1 goes to /dev/null. No later line CAN leak, and the single
# deliberate emission at the bottom is the only thing addressed to `>&3`.
exec 3>&1 >/dev/null

# Decimal separators and collation: pinned for the same reason inline_shadow
# pins them -- a comma-decimal locale turns a timestamp into something that is
# not a JSON number.
export LC_ALL=C

# $ROOT is THE PROJECT the session is running in. It is what the per-project
# opt-out and the cwd guard are anchored on, and nothing else.
ROOT="${CLAUDE_PROJECT_DIR:-}"

# --- jev home: canonical block, byte-identical in every hook ----------------
# W2/JEV-56. $JEV_HOME is WHERE JEV ITSELF LIVES, resolved WITHOUT reference to
# $CLAUDE_PROJECT_DIR. The two are the same directory only when jev is running
# in its own repo; once `jev install` registers this hook in somebody else's
# repo they are different, and every asset below -- config/tiers.json, the
# assignment ledger, the breaker log, the stderr log -- belongs to jev, not to
# the project being routed.
#
# The pivot audit found the failure this prevents: resolve jev's root from
# $CLAUDE_PROJECT_DIR and, in the wrong install shape, `config/tiers.json`
# names a file that does not exist (so every delegation fails to frontier),
# the ledger is written into somebody else's working tree, and the kill switch
# names a path that will never exist -- a switch that is permanently off.
#
# ONE MECHANISM, BOTH READERS. `src/paths.py` resolves JEV_HOME with the same
# two-line rule -- the environment variable if it names a directory, otherwise
# the directory two levels above this file -- so the bash half and the Python
# half cannot disagree. `tests/test_jev_home.sh` asserts they return the same
# absolute path, and `paths.jev_home_source()` reports which arm fired.
#
# FAIL SAFE, like everything else here: a $JEV_HOME that cannot be established
# is not guessed at, it is an exit.
#
# W5. A RELATIVE $JEV_HOME IS REFUSED, NOT NORMALISED, AND THE REASON IS THE
# KILL SWITCH. Bash uses the value VERBATIM after an `is_dir` test, so
# `JEV_HOME=.` makes every jev asset cwd-relative -- config/tiers.json, the
# ledger, the breaker log, and `$JEV_HOME/.jev-disabled`, which is the GLOBAL
# kill switch. A switch whose path depends on where the caller happened to be
# standing is precisely what the per-project block below says must never
# happen: "anchored on $ROOT, never cwd-relative". `src/paths.py` RAISES on
# the same value rather than silently `.resolve()`-ing it against the cwd, so
# the two readers agree that there is exactly one kind of $JEV_HOME that means
# the same thing to both -- an absolute one. A hook cannot raise, so it
# refuses. Not a fallback: falling back to the derived path would be this
# reader guessing where the other one declines to, and `jev` and
# `paths.resolve_jev_home()` already reject the value loudly at the point a
# human sets it.
JEV_HOME="${JEV_HOME:-}"
case "$JEV_HOME" in ""|/*) ;; *) exit 0 ;; esac
[ -d "$JEV_HOME" ] || JEV_HOME="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd -P)"
[ -n "$JEV_HOME" ] || exit 0
[ -d "$JEV_HOME" ] || exit 0
# --- end jev home -----------------------------------------------------------

if [ -d "$JEV_HOME/logs" ]; then
  exec 2>>"$JEV_HOME/logs/agent_route.err"
else
  exec 2>/dev/null
fi

# Recursion guard. The cc_* arms shell out to `claude -p`, which starts a real
# Claude Code session -- one that would load this project's hooks and have its
# own delegations rewritten by the actuator under measurement. Env vars are
# inherited, so the guard holds however deep the spawn goes.
[ -n "$JEV_ARM_SUBPROCESS" ] && exit 0

# The blinded grader's own delegations must not be routed by the thing it is
# grading. Same shape as the recursion guard, different reason.
[ -n "$JEV_GRADER" ] && exit 0

[ -n "$ROOT" ] || exit 0
[ -d "$ROOT" ] || exit 0

# --- jev GLOBAL kill switch: canonical block, byte-identical in every hook ---
# SWITCH ONE OF TWO, and the one that does not depend on which repo you are in.
# It stops routing in EVERY project at once, which is what you want at 3am when
# you do not yet know which repo is misbehaving. The per-project block below is
# the other one: an opt-out for a single repo, which is a different question.
#
# Two paths, either of which is enough:
#
#   $JEV_HOME/.jev-disabled        what `./teardown.sh` and `jev uninstall`
#                                  set. JEV_HOME-anchored, NOT project-anchored,
#                                  so it is a real path in every install shape.
#                                  Under the rejected global install this is
#                                  precisely the switch that would have named a
#                                  file that can never exist.
#   $HOME/.claude/jev-disabled     machine-wide, set by hand, honoured even if
#                                  the jev install itself is unreachable.
#                                  Read-only; nothing in this repo writes here.
#
# Same fail-safe rule as the per-project switch below: ANY entry at either path
# means OFF, and a state that cannot be established ALSO means OFF -- hence the
# unset-HOME case. A switch is never given the benefit of the doubt.
[ -n "$HOME" ] || exit 0
{ [ -e "$JEV_HOME/.jev-disabled" ] || [ -L "$JEV_HOME/.jev-disabled" ]; } && exit 0
{ [ -e "$HOME/.claude/jev-disabled" ] || [ -L "$HOME/.claude/jev-disabled" ]; } && exit 0
# --- end jev GLOBAL kill switch ---------------------------------------------

# --- jev kill switch: canonical block, byte-identical in every hook ----------
# One switch, all surfaces. `tests/reversibility.sh` enumerates the registered
# hooks and fails if any of them lacks this block, so a new surface cannot be
# added without it.
#
# Anchored on $ROOT, never cwd-relative: a hook fires with whatever cwd the
# session happens to have, and a relative test silently stops working the moment
# you cd into a subdirectory.
#
# FAIL SAFE (JEV-40): ANY entry at this path means OFF. `-f` alone reads a
# directory as absent, so an operator who ran `mkdir .jev-disabled` would
# believe the switch was set while the hook kept firing; `-e` alone reads a
# dangling symlink as absent. An unreadable file still stats, so it too reads as
# present. When the state of the switch cannot be established, the answer is
# OFF, not ON -- the switch is never given the benefit of the doubt.
{ [ -e "$ROOT/.jev-disabled" ] || [ -L "$ROOT/.jev-disabled" ]; } && exit 0
# --- end jev kill switch ----------------------------------------------------

# Jev's own assets, under $JEV_HOME and never under the routed project. The
# rule table is jev's, the ledger is jev's, and an install into somebody else's
# repo must not put either of them in their working tree.
#
# These are defined HERE, above the cwd guard rather than below it, because the
# guard now has to be able to write down that it fired. See `inert` below.
CFG="$JEV_HOME/config/tiers.json"
DIR="$JEV_HOME/data/agent_route"
LEDGER_DIR="$DIR/assignments"
BREAKER="$DIR/breaker.jsonl"
MARKER="$DIR/BREAKER-OPEN"
INERT_LOG="$DIR/inert.jsonl"
INERT_MARKER="$DIR/INERT"

# ---------------------------------------------------------------------------
# A SILENT NO-OP IS NEVER AN ACCEPTABLE ANSWER
# ---------------------------------------------------------------------------
# FAIL SAFE and FAIL SILENTLY are not the same thing, and this repo has now
# been bitten four times by the second one wearing the first one's clothes.
#
# Several paths in this hook cannot fail to frontier: there is no faithful
# `updatedInput` to build (no jq), or the hook has decided it is out of scope
# (cwd guard), or it cannot write the ledger that a rewrite must be
# attributable to. Doing nothing is the RIGHT action on all of them. Doing
# nothing INVISIBLY is not: a registered hook that is a permanent no-op is
# byte-identical to the control arm while appearing installed, which is
# precisely the state the `resolvedModel` check exists to catch, arriving
# through a different door.
#
# So every such path comes through here, and the contract is:
#
#   a DURABLE record (a jsonl row plus a sticky marker file), or -- if the
#   disk will not take one -- the LOUDEST channel a hook has, a systemMessage.
#
# Never both-fail quietly. The systemMessage carries no interpolated paths: it
# is assembled from literals so it cannot be made into malformed JSON by a
# directory name, and stdout on a PreToolUse hook is a permission decision.
inert() { # reason, detail
  _reason="$1"; _detail="$2"; _wrote=""
  _its=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) || _its="unknown"
  # Paths go into JSON, so the two characters that could tear the row are
  # escaped. Parameter expansion, not a fork: this path is already the
  # unhappy one and does not need to be slow as well.
  _j="$JEV_HOME"; _j="${_j//\\/\\\\}"; _j="${_j//\"/\\\"}"
  _r="$ROOT";     _r="${_r//\\/\\\\}"; _r="${_r//\"/\\\"}"
  _w="$PWD";      _w="${_w//\\/\\\\}"; _w="${_w//\"/\\\"}"
  if mkdir -p "$DIR" 2>/dev/null; then
    if printf '{"schema":"agent-route-inert-v1","timestamp":"%s","reason":"%s","detail":"%s","jev_home":"%s","project_dir":"%s","cwd":"%s","pid":%s}\n' \
         "$_its" "$_reason" "$_detail" "$_j" "$_r" "$_w" "$$" >> "$INERT_LOG" 2>/dev/null; then
      _wrote="yes"
      printf '%s jev agent_route is INERT: %s\n%s\nThe hook is registered and is routing nothing. No assignment is being recorded, so this condition is invisible in the ledger -- which is why this file exists. Remove it once the cause is fixed; it is rewritten on every occurrence.\n' \
        "$_its" "$_reason" "$_detail" > "$INERT_MARKER" 2>/dev/null
    fi
  fi
  if [ -z "$_wrote" ]; then
    case "$_reason" in
      cwd_outside_project) printf '%s\n' '{"systemMessage":"jev agent_route is INERT (the session cwd is outside $CLAUDE_PROJECT_DIR) and cannot write its own record of that. No delegation is being routed."}' >&3 ;;
      project_dir_unresolvable) printf '%s\n' '{"systemMessage":"jev agent_route is INERT ($CLAUDE_PROJECT_DIR does not resolve) and cannot write its own record of that. No delegation is being routed."}' >&3 ;;
      no_jq)               printf '%s\n' '{"systemMessage":"jev agent_route is INERT (jq is not on PATH) and cannot write its own record of that. No delegation is being routed."}' >&3 ;;
      ledger_dir_unwritable|ledger_write_failed) printf '%s\n' '{"systemMessage":"jev agent_route is INERT (it cannot write its assignment ledger, and an unattributable rewrite is forbidden) -- so no delegation is being routed. Check the permissions on $JEV_HOME/data/agent_route."}' >&3 ;;
      *)                   printf '%s\n' '{"systemMessage":"jev agent_route is INERT and cannot write its own record of that. No delegation is being routed."}' >&3 ;;
    esac
  fi
  exit 0
}

# Defensive cwd guard, as capture.sh. settings.local.json should never load
# outside this repo, but the isolation requirement is hard enough to be worth
# enforcing twice -- and this hook changes what runs, not merely what is logged.
#
# TWO DEFECTS FIXED HERE, AND THE SECOND IS THE DANGEROUS ONE.
#
# 1. It was a BYTE comparison of two paths that are only semantically equal.
#    `CLAUDE_PROJECT_DIR=/repo/` (a trailing slash) or a symlinked checkout
#    made "$PWD/" fail to match "$ROOT"/* for a session that was squarely
#    inside the project, and the hook exited here on every single invocation.
#    Both sides are now resolved with `pwd -P`, which normalises the slash and
#    the symlink at once. Two subshells, paid once per Agent spawn, against a
#    250ms budget.
# 2. Exiting here was TOTALLY SILENT: zero bytes, no ledger row, no breaker
#    line, no marker. A permanent no-op with nothing on disk, treatment
#    byte-identical to control while appearing installed. Now it goes through
#    `inert`, which leaves a record or says so out loud.
ROOT_P=$(cd "$ROOT" 2>/dev/null && pwd -P) || ROOT_P=""
[ -n "$ROOT_P" ] || inert "project_dir_unresolvable" \
  "CLAUDE_PROJECT_DIR names a directory that could not be resolved with cd/pwd -P"
PWD_P=$(pwd -P 2>/dev/null) || PWD_P="$PWD"
case "$PWD_P/" in
  "$ROOT_P"/*) ;;
  *) inert "cwd_outside_project" \
       "the resolved cwd is not inside the resolved CLAUDE_PROJECT_DIR; this hook routes nothing outside the project it was registered for" ;;
esac

# jq is the only way to echo an arbitrary tool input back byte-faithfully. With
# no jq there is no faithful updatedInput to build, so the hook goes inert
# rather than guessing -- see the fail-safe/fail-to-frontier note above. Inert,
# and SAYING SO: "no jq on this machine" is a fixable condition, and a router
# that silently stops routing because of it is a router nobody fixes.
command -v jq >/dev/null 2>&1 || inert "no_jq" \
  "jq is not on PATH, so no byte-faithful updatedInput can be built"

# THE ONE TIER LITERAL IN THIS SCRIPT, AND IT IS DELIBERATE.
# Everything else is configuration. This is the fail-to-frontier target used
# when config/tiers.json is the thing that failed -- and a fail-safe value
# cannot itself depend on the thing that failed. "opus" is the frontier ALIAS,
# matching tiers.opus5.alias; if you change the frontier tier in config, change
# this too, and tests/test_agent_actuator.py asserts the two agree.
FRONTIER_FALLBACK_ALIAS="opus"
# Breaker defaults for the same path: when config cannot be read, its breaker
# settings cannot be read either, and an unbounded fail-to-frontier is the exact
# outage the breaker exists to stop.
BREAKER_N_FALLBACK=3
BREAKER_TTL_FALLBACK=900

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# One extra fork to get a sub-second clock: /bin/bash on macOS is 3.2, with no
# EPOCHREALTIME and no printf %()T, and BSD date has no %N. inline_shadow_bash.sh
# pays the same fork for the same reason. `hook_ms` travels on every ledger row
# so the latency budget in config/tiers.json is a measurement, not an intention.
T0=$(jq -n 'now' 2>/dev/null) || T0=0

PAYLOAD=$(cat)
[ -n "$PAYLOAD" ] || exit 0

# Defensive: this hook is registered with matcher `Agent` and should never see
# anything else, but a matcher is a regex in a settings file and settings files
# get edited. Rewriting `model` on some other tool's input would be a silent
# corruption, so anything that is not an Agent spawn is left strictly alone --
# and is not a router failure either, because nothing was asked of the router.
case "$PAYLOAD" in
  *'"tool_name":"Agent"'*|*'"tool_name": "Agent"'*) ;;
  *) exit 0 ;;
esac

# THE LEDGER DIRECTORY, AND THE THIRD SILENT NO-OP.
# This `mkdir` used to be unchecked. With `$JEV_HOME/data/agent_route/`
# unwritable it failed, then the ledger append failed, then the breaker append
# that was supposed to record THAT failed too -- and the hook exited 0 having
# left nothing anywhere. A routing layer that cannot record an assignment must
# not make one (an unattributable rewrite is what the before-spawn ledger
# exists to forbid), but it must not be quiet about it either.
mkdir -p "$LEDGER_DIR" 2>/dev/null || inert "ledger_dir_unwritable" \
  "mkdir -p on the assignment ledger directory failed; no assignment can be recorded, so none is made"
LEDGER="$LEDGER_DIR/${TS%%T*}.jsonl"

# Content hash of the rule table, so a decision can later be joined to the exact
# rule text that produced it. openssl, not shasum: shasum is a perl script and
# pays ~25ms of interpreter startup on a path whose budget is measured in
# milliseconds. src/tier_map.config_sha256() computes the same digest with
# hashlib and a test asserts they agree.
CFG_SHA=""
if [ -f "$CFG" ]; then
  CFG_SHA_LINE=$(openssl dgst -sha256 "$CFG" 2>/dev/null)
  CFG_SHA="${CFG_SHA_LINE##* }"
fi

# The tail of the breaker log. `tail` rather than a bash read loop: the log is
# append-only and unbounded, and reading all of it in the shell would make the
# hook slower the longer it has been installed. 50 lines bounds the window;
# tests/test_agent_actuator.py asserts max_consecutive_failures stays well
# inside it.
BREAKER_TAIL=$(tail -n 50 "$BREAKER" 2>/dev/null)

# The breaker predicate, defined ONCE and spliced into both jq programs below.
# The fallback program cannot read the config, so it must still be able to open
# the breaker with literal defaults -- otherwise a permanently broken config
# would fail to frontier forever with the breaker never engaging. Sharing the
# text rather than retyping it is what stops the two copies drifting.
JQ_BREAKER='
  def breaker_state($log; $n; $ttl; $now):
    ($log | split("\n") | map(select(length > 0) | (fromjson? // empty))
          | sort_by(.ts // 0)) as $bo
    | ($bo | reverse) as $rev
    | ([ $rev | to_entries[] | select(.value.ok == true) | .key ]
       | (.[0] // ($rev | length))) as $consec
    | (if ($bo | length) > 0 then (($bo | last).ts // 0) else 0 end) as $newest
    | (($now - $newest) < $ttl) as $fresh
    | {open: (($n > 0) and ($consec >= $n) and $fresh and (($bo | length) >= $n)),
       consecutive: $consec, newest: $newest};
'

# Three lines out of jq, always, in this order:
#   1. the assignment ledger row (JSON)
#   2. what to write to the real stdout, or "-" for nothing
#   3. the breaker outcome line to append, or "-" for nothing
#
# "-" for nothing rather than an empty line, because an empty line is also what
# a truncated jq run produces and the two must not be confusable.
JQ_DECIDE='
  $cfg[0] as $c
  | (.tool_input) as $ti
  | if ($ti | type) != "object" then error("no tool_input") else . end
  | if (($c.tiers | type) != "object") or (($c.rules | type) != "object")
       or (($c.tiers[$c.frontier_tier] | type) != "object")
    then error("unusable tiers.json") else . end
  # A TIER WITH NO `alias` IS A BROKEN RULE TABLE, NOT A ROUTING DECISION.
  # This branch used to be missing and the hook FAILED OPEN through it: the
  # decision came out `routed` with `assigned_alias: null`, nothing was
  # rewritten, nothing was emitted, and the breaker line said `ok: true` -- so
  # the one condition that makes routing a permanent no-op was counted as a
  # SUCCESS and could never trip the breaker. `src/tier_map.alias_for()` has
  # always RAISED on exactly this config, so the two implementations disagreed
  # and the parity test did not cover it. Raising here sends it to
  # JQ_FRONTIER, which is what non-negotiable 1(b) requires: a router that
  # cannot decide sends the task to frontier.
  | if (($c.tiers[$c.frontier_tier].alias // "") == "")
    then error("frontier tier has no alias") else . end
  | (($c.breaker.max_consecutive_failures // 3) | floor) as $bn
  | (($c.breaker.ttl_s // 900) | tonumber) as $bttl
  | breaker_state($breaker; $bn; $bttl; now) as $br
  | ($ti.subagent_type // null) as $st
  | (if (($ti.model // "") == "") then null else $ti.model end) as $orig
  # `inherit` sits in tool_input.model but expresses no tier preference -- it
  # means "use whatever model the parent is on". Treating it as a deliberate
  # caller choice would exclude those spawns from routing forever while looking
  # like deference to the caller. Still recorded as original_model either way.
  # (No apostrophes in this program: it is a single-quoted shell string.)
  | (($c.explicit_model_ignored_values // ["inherit"])) as $ignored
  | (($orig != null) and (($ignored | index($orig)) == null)) as $chose
  | (if $br.open then
       {outcome: "breaker_open", tier: null, alias: null,
        rule: ("breaker OPEN: " + ($br.consecutive | tostring)
               + " consecutive failures, threshold " + ($bn | tostring))}
     elif ($chose and (($c.explicit_model_action // "keep") == "keep")) then
       {outcome: "explicit_model_kept", tier: null, alias: null,
        rule: ("explicit_model_action=keep; caller asked for " + ($orig | tojson))}
     else
       ($c.rules[$st // ""] // null) as $rule
       | if $rule == null then
           (if (($c.unmapped_action // "leave") == "frontier") then
              {outcome: "routed", tier: $c.frontier_tier,
               alias: $c.tiers[$c.frontier_tier].alias,
               rule: ("unmapped_action=frontier for subagent_type=" + ($st | tojson))}
            else
              {outcome: "no_rule", tier: null, alias: null,
               rule: ("unmapped_action=leave; no rule for subagent_type=" + ($st | tojson))}
            end)
         elif ($rule.tier == null) then
           {outcome: "no_rule", tier: null, alias: null,
            rule: ("rules[" + ($st | tojson) + "].tier=null (no routing signal)")}
         elif (($c.tiers[$rule.tier] | type) != "object") then
           error("rule names unknown tier")
         elif (($c.tiers[$rule.tier].alias // "") == "") then
           # The tier exists and has no alias: there is nothing to put in
           # tool_input.model. Same class as an unknown tier, so the same
           # answer -- and the same answer src/tier_map.alias_for() has always
           # given, which is to raise.
           error("rule names tier with no alias")
         else
           {outcome: "routed", tier: $rule.tier, alias: $c.tiers[$rule.tier].alias,
            rule: ("rules[" + ($st | tojson) + "].tier=" + ($rule.tier | tojson))}
         end
     end) as $d
  # BELT AND BRACES, because this is the shape that failed open once already.
  # `routed` means "the input was rewritten". A `routed` decision carrying no
  # alias rewrites nothing, emits nothing, and -- worst of all -- logs
  # `ok: true`, so the router is permanently inert AND scored as succeeding.
  # No config can reach here any more; if a future edit finds a way, this
  # raises and the task goes to frontier instead of quietly doing nothing.
  | (if (($d.outcome == "routed") and ($d.alias == null))
     then error("routed with no alias") else . end)
  | {schema: "agent-route-assignment-v2",
     timestamp: $ts,
     session_id: (.session_id // null),
     tool_use_id: (.tool_use_id // null),
     subagent_type: $st,
     decision: $d.outcome,
     tier: $d.tier,
     assigned_alias: $d.alias,
     rule: $d.rule,
     original_model: $orig,
     config_version: ($c.version // null),
     config_sha256: (if $sha == "" then null else $sha end),
     hook_ms: ((now - ($t0 | tonumber)) * 1000),
     # JEV-57. WHICH REPO THIS DECISION WAS MADE IN, recorded at decision
     # time and never inferred later. The ledger lives at
     # $JEV_HOME/data/agent_route/ -- ONE directory shared by every repo jev
     # is installed in -- so without this field the delegations of two
     # different repos pool into one rate, which is the JEV-32 confound
     # wearing a different hat. It looks like a result.
     #
     # $ROOT RAW, not the `pwd -P`-resolved $ROOT_P the cwd guard uses: the
     # path of a worktree is not the path of its repository, and normalising
     # the two together is an analysis decision made with knowledge this hook
     # does not have. Recording where the decision happened, exactly, leaves
     # that decision to the reader who can make it.
     # (No apostrophes in this program: it is a single-quoted shell string.)
     project: (if $project == "" then null else $project end)} as $row
  | $row,
    (if $d.alias != null then
       # `$ti + {model: ...}` is a RIGHT-BIASED MERGE over the whole object, so
       # every key the caller sent survives by construction -- there is no
       # field list here that could fall out of date. This is the
       # input-fidelity gate: updatedInput replaces the ENTIRE tool input, and
       # a dropped `subagent_type` spawns the wrong agent type.
       ({hookSpecificOutput: {hookEventName: "PreToolUse",
                              permissionDecision: "allow",
                              updatedInput: ($ti + {model: $d.alias})}} | tojson)
     elif $d.outcome == "breaker_open" then
       # The loudest channel a hook has. No updatedInput: the input is left
       # exactly as it arrived, so hook_dispatch treats this as "unchanged" and
       # the OFF-is-vanilla byte-identity claim still holds.
       ({systemMessage: ("jev routing breaker OPEN (" + ($br.consecutive | tostring)
                         + " consecutive router failures) -- static routing is "
                         + "SUSPENDED and every delegation is running at its "
                         + "default tier. See data/agent_route/BREAKER-OPEN.")} | tojson)
     else "-" end),
    (if ($d.outcome == "breaker_open") then
       # Deliberately append nothing while open: another failure line would
       # push the newest timestamp forward and the TTL could never expire.
       "-"
     else
       ({ts: now, ok: ($d.outcome != "fail_to_frontier"),
          error: (if $d.outcome == "fail_to_frontier" then $d.rule else null end)}
        | tojson)
     end)
'

# The fallback: payload parsed, config did not. Everything the caller sent is
# echoed and `model` goes to the frontier alias. Reached only when JQ_DECIDE
# raised -- and if the payload is what is broken, this raises too and the hook
# emits nothing at all, which is the correct answer.
JQ_FRONTIER='
  (.tool_input) as $ti
  | if ($ti | type) != "object" then error("no tool_input") else . end
  | breaker_state($breaker; ($bn | tonumber); ($bttl | tonumber); now) as $br
  | (if $br.open then
       {outcome: "breaker_open", alias: null,
        rule: ("breaker OPEN: " + ($br.consecutive | tostring) + " consecutive failures")}
     else
       {outcome: "fail_to_frontier", alias: $frontier,
        rule: ("fail_to_frontier: " + $why)}
     end) as $d
  | {schema: "agent-route-assignment-v2",
     timestamp: $ts,
     session_id: (.session_id // null),
     tool_use_id: (.tool_use_id // null),
     subagent_type: ($ti.subagent_type // null),
     decision: $d.outcome,
     tier: null,
     assigned_alias: $d.alias,
     rule: $d.rule,
     original_model: (if (($ti.model // "") == "") then null else $ti.model end),
     config_version: null,
     config_sha256: (if $sha == "" then null else $sha end),
     hook_ms: ((now - ($t0 | tonumber)) * 1000),
     # JEV-57, as above. The fallback path needs it just as much: a
     # fail-to-frontier row that cannot be attributed to a repo is a
     # frontier-rate assignment pooled across installs.
     # (No apostrophes in this program either.)
     project: (if $project == "" then null else $project end)},
    (if $d.alias != null then
       ({hookSpecificOutput: {hookEventName: "PreToolUse",
                              permissionDecision: "allow",
                              updatedInput: ($ti + {model: $d.alias})}} | tojson)
     elif $d.outcome == "breaker_open" then
       ({systemMessage: ("jev routing breaker OPEN (" + ($br.consecutive | tostring)
                         + " consecutive router failures) -- static routing is "
                         + "SUSPENDED and every delegation is running at its "
                         + "default tier. See data/agent_route/BREAKER-OPEN.")} | tojson)
     else "-" end),
    (if $d.outcome == "breaker_open" then "-"
     else ({ts: now, ok: false, error: $d.rule} | tojson) end)
'

RESULT=$(printf '%s' "$PAYLOAD" | jq -r -c \
  --slurpfile cfg "$CFG" \
  --arg ts "$TS" --arg sha "$CFG_SHA" --arg t0 "$T0" \
    --arg project "$ROOT" \
  --arg breaker "$BREAKER_TAIL" \
  "$JQ_BREAKER $JQ_DECIDE" 2>/dev/null)

if [ -z "$RESULT" ]; then
  WHY="tiers.json missing or unusable"
  [ -f "$CFG" ] || WHY="tiers.json not found at config/tiers.json"
  RESULT=$(printf '%s' "$PAYLOAD" | jq -r -c \
    --arg ts "$TS" --arg sha "$CFG_SHA" --arg t0 "$T0" \
    --arg project "$ROOT" \
    --arg breaker "$BREAKER_TAIL" \
    --arg frontier "$FRONTIER_FALLBACK_ALIAS" --arg why "$WHY" \
    --arg bn "$BREAKER_N_FALLBACK" --arg bttl "$BREAKER_TTL_FALLBACK" \
    "$JQ_BREAKER $JQ_FRONTIER" 2>/dev/null)
fi

# Still nothing: the payload itself is unparseable. There is no faithful
# updatedInput to build, so the hook emits ZERO bytes and the tool input is
# untouched. Recorded as a router failure so a run of malformed payloads opens
# the breaker rather than quietly disappearing.
if [ -z "$RESULT" ]; then
  printf '{"ts":%s,"ok":false,"error":"unparseable_payload"}\n' \
    "${T0:-0}" >> "$BREAKER" 2>/dev/null
  exit 0
fi

ROW="${RESULT%%$'\n'*}"
REST="${RESULT#*$'\n'}"
EMIT="${REST%%$'\n'*}"
OUTCOME="${REST#*$'\n'}"

# --- THE ASSIGNMENT LEDGER, WRITTEN BEFORE THE SPAWN ------------------------
# Not after. A ledger written afterwards is missing exactly when it matters
# most: when the task crashed. Everything below this point is ordered so that
# the durable record exists before the decision can take effect.
printf '%s\n' "$ROW" >> "$LEDGER" 2>/dev/null
LEDGER_RC=$?

if [ "$LEDGER_RC" -ne 0 ]; then
  # The ledger could not be written. Three options were available: rewrite
  # anyway (an unattributable assignment, which is precisely what the
  # before-spawn gate forbids), block the call (never -- fail safe is
  # absolute), or leave the input untouched. Untouched wins: it is the control
  # arm.
  #
  # What was NOT true is the sentence that used to end that paragraph: "its
  # absence from the ledger is itself the honest record". An absence is not a
  # record. If the breaker append below also fails -- and it fails for exactly
  # the same reason the ledger append did, an unwritable directory -- the hook
  # has done nothing and said nothing. So the breaker line is still attempted,
  # and then `inert` guarantees either a durable row or a systemMessage.
  printf '{"ts":%s,"ok":false,"error":"ledger_write_failed"}\n' \
    "${T0:-0}" >> "$BREAKER" 2>/dev/null
  inert "ledger_write_failed" \
    "the assignment ledger could not be appended to; a rewrite that cannot be attributed is forbidden, so the input was left untouched"
fi

[ "$OUTCOME" = "-" ] || printf '%s\n' "$OUTCOME" >> "$BREAKER" 2>/dev/null

# The sticky marker: a breaker open only in a transcript is a breaker nobody
# finds tomorrow morning. src/doctor.py reads this file.
case "$ROW" in
  *'"decision":"breaker_open"'*)
    printf '%s jev routing breaker OPEN -- static routing suspended, every delegation at its default tier.\nClear by fixing the cause; the breaker closes itself on the first successful decision after the TTL.\n' \
      "$TS" > "$MARKER" 2>/dev/null ;;
  *) rm -f "$MARKER" 2>/dev/null ;;
esac

# The single deliberate emission, on the only fd that reaches Claude Code.
[ "$EMIT" = "-" ] || printf '%s\n' "$EMIT" >&3

exit 0
