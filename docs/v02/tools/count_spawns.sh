#!/usr/bin/env bash
# count_spawns.sh [DAYS]   (default 21)
# READ-ONLY. Counts DISTINCT Agent tool_use blocks (dedupe by tool_use id) per project
# directory in the main session transcripts ~/.claude/projects/*/*.jsonl over the last DAYS days.
# Prints: decoded project directory, count, breakdown general-purpose / absent / other.
# Never prints prompts or message text; never writes anywhere (no temp files).
# Needs bash + jq + find + grep + awk + sort. Works on macOS (BSD date) and Linux (GNU date).
DAYS="${1:-21}"
case "$DAYS" in ''|*[!0-9]*) echo "usage: $0 [DAYS]" >&2; exit 2;; esac
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }
ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
[ -d "$ROOT" ] || { echo "no such directory: $ROOT" >&2; exit 1; }

CUTOFF="$(date -u -v-"${DAYS}"d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "${DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
[ -n "$CUTOFF" ] || { echo "could not compute cutoff date" >&2; exit 1; }

# Best-effort decode of an encoded project dir name (every non-alphanumeric char became '-').
# Uses the filesystem (read-only stat) to disambiguate real hyphens from path separators;
# falls back to a naive replace. Names containing '_' or spaces may decode imperfectly.
decode_rec() { # base index ; uses global tok[] n
  local base="$1" i="$2" j seg="" cand r
  if [ "$i" -ge "$n" ]; then printf '%s' "$base"; return 0; fi
  for ((j=i; j<n; j++)); do
    if [ "$j" -eq "$i" ]; then seg="${tok[j]}"; else seg="$seg-${tok[j]}"; fi
    cand="$base/$seg"
    if [ "$j" -eq $((n-1)) ]; then
      [ -d "$cand" ] && { printf '%s' "$cand"; return 0; }
    else
      [ -d "$cand" ] && { r="$(decode_rec "$cand" $((j+1)))" && [ -n "$r" ] && { printf '%s' "$r"; return 0; }; }
    fi
  done
  return 1
}
decode() {
  local enc="$1" e r
  e="${enc//--/-.}"; e="${e#-}"
  IFS=- read -r -a tok <<<"$e"; n=${#tok[@]}
  r="$(decode_rec "" 0)" && [ -n "$r" ] && { printf '%s' "$r"; return; }
  printf '/%s' "$(printf '%s' "${enc#-}" | tr - /)"
}

echo "# Agent spawns per project directory, last ${DAYS} days (since ${CUTOFF})"
echo "# counts only; use this list to choose a per-repo allowlist; exclude repos holding personal data, credentials, or agent workspaces"
echo "# columns: count | general-purpose | absent | other | project directory"

total=0; tgp=0; tabs=0; toth=0
rows=""
for d in "$ROOT"/*/; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  # mtime prefilter (file mtime >= newest event), one day of slack; exact filter is the jq timestamp compare.
  res="$(find "$d" -maxdepth 1 -type f -name '*.jsonl' -mtime -"$((DAYS+1))" -exec grep -h '"name":"Agent"' {} + 2>/dev/null \
    | jq -R -r --arg c "$CUTOFF" 'fromjson? | select(type=="object" and .type=="assistant" and ((.timestamp // "") >= $c))
        | .message.content[]? | select(type=="object" and .type=="tool_use" and .name=="Agent")
        | [.id, ((.input.subagent_type // "") | if .=="" then "absent" elif .=="general-purpose" then "gp" else "other" end)] | @tsv' 2>/dev/null \
    | sort -u -t"$(printf '\t')" -k1,1 \
    | awk -F'\t' '{n++; if($2=="gp")g++; else if($2=="absent")a++; else o++} END{if(n>0) printf "%d %d %d %d", n, g+0, a+0, o+0}')"
  [ -n "$res" ] || continue
  set -- $res
  total=$((total+$1)); tgp=$((tgp+$2)); tabs=$((tabs+$3)); toth=$((toth+$4))
  rows="$rows$1	$2	$3	$4	$(decode "$name")
"
done
printf '%s' "$rows" | sort -t"$(printf '\t')" -k1,1nr | awk -F'\t' 'NF==5{printf "%5d | %5d | %5d | %5d | %s\n",$1,$2,$3,$4,$5}'
echo "# TOTAL: $total spawns (general-purpose=$tgp, absent=$tabs, other=$toth)"
