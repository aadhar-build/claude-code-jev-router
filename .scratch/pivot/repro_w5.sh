#!/bin/bash
# W5 scratch repro. Throwaway.
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
S="$(mktemp -d)"
echo "sandbox: $S"

echo "=============== DEFECT 1: tier B aborts on the ordinary case ==============="
R="$S/repo1"; mkdir -p "$R"
"$REPO/jev" install "$R" --yes >/dev/null 2>&1
python3 - "$R/.claude/settings.local.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["hooks"].setdefault("PreToolUse", []).append(
    {"matcher": "Write", "hooks": [{"type": "command", "command": "their-own-hook.sh"}]})
json.dump(d, open(p, "w"), indent=2)
PY
"$REPO/jev" uninstall "$R" --yes
echo "EXIT=$?"
echo "--- settings after uninstall ---"
cat "$R/.claude/settings.local.json"
echo "--- is jev still registered? ---"
grep -c agent_route_actuator "$R/.claude/settings.local.json"

echo
echo "=============== DEFECT 2: is_ours substring, deletes on install ==============="
R2="$S/repo2"; mkdir -p "$R2/.claude"
cat > "$R2/.claude/settings.local.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Write",
        "hooks": [ { "type": "command", "command": "/my/own/hooks/agent_route_actuator.sh --mine" } ] }
    ]
  }
}
EOF
"$REPO/jev" install "$R2" --yes
echo "--- settings after install ---"
cat "$R2/.claude/settings.local.json"
echo "--- is their hook still there? (expect 1) ---"
grep -c -- "--mine" "$R2/.claude/settings.local.json"

echo
echo "=============== EXTRA: symlinked jev ==============="
mkdir -p "$S/bin"
ln -s "$REPO/jev" "$S/bin/jev"
"$S/bin/jev" status "$S" 2>&1 | head -20
echo "EXIT=$?"

echo
echo "=============== EXTRA: JEV_HOME=. ==============="
cd "$S" && JEV_HOME=. "$REPO/jev" status "$S" 2>&1 | head -12

echo
echo "sandbox left at $S"
