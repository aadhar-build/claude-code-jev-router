#!/bin/bash
# W5 scratch: full copy of the working tree (so gitignored data/ fixtures are
# present), with every file OTHER agents are mid-edit on reverted to HEAD.
# What remains is HEAD + W5's six files, and the suite can be read honestly.
R="$(cd "$(dirname "$0")/../.." && pwd -P)"
T="$(mktemp -d)/tree"
mkdir -p "$T"
tar -C "$R" -cf - . | tar -C "$T" -xf -

MINE=" src/install.py src/paths.py jev config/registration.json tests/test_install.sh tests/test_jev_home.sh "
for f in $(git -C "$R" diff --name-only HEAD); do
  case "$MINE" in *" $f "*) continue ;; esac
  git -C "$R" show "HEAD:$f" > "$T/$f" 2>/dev/null || rm -f "$T/$f"
  echo "reverted to HEAD: $f"
done
chmod +x "$T/jev" "$T"/hooks/*.sh "$T"/tests/*.sh 2>/dev/null
echo "tree at $T"
cd "$T" && bash tests/run_all.sh 2>&1 | tail -30
