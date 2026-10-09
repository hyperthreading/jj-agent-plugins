# Shared helpers for jj-agent hooks. Sourced, not executed. bash 3.2 compatible (macOS /bin/bash).
# Expects HOOK_INPUT to hold the hook's stdin JSON.

# First value of a string field anywhere in the input (top-level fields come first).
json_get() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$HOOK_INPUT" | jq -r --arg k "$1" 'first(.. | objects | select(has($k)) | .[$k] | strings) // empty' 2>/dev/null
  else
    printf '%s' "$HOOK_INPUT" | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -n 1 |
      sed -e 's/^[^:]*:[[:space:]]*"//' -e 's/"$//'
  fi
}

# A string field of tool_input (falls back to the first match anywhere without jq).
tool_input_get() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$HOOK_INPUT" | jq -r --arg k "$1" '.tool_input[$k]? // empty | strings' 2>/dev/null
  else
    json_get "$1"
  fi
}

json_str() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'BEGIN{ORS="\\n"} {print}' | sed 's/\\n$//'; }

# Print the jj workspace root containing $1 (walks up looking for .jj; no jj process). Fails if none.
find_jj_root() {
  local d
  [ -n "$1" ] || return 1
  d=$(cd "$1" 2>/dev/null && pwd -P) || return 1
  while :; do
    if [ -d "$d/.jj" ]; then printf '%s\n' "$d"; return 0; fi
    [ "$d" = "/" ] && return 1
    d=$(dirname "$d")
  done
}

# Per-session record of which jj roots Claude has already been told about.
state_file() {
  local dir="${CLAUDE_PLUGIN_DATA:-${TMPDIR:-/tmp}/jj-agent}/sessions"
  mkdir -p "$dir" 2>/dev/null
  printf '%s/%s' "$dir" "$(printf '%s' "${SESSION_ID:-default}" | tr -c 'A-Za-z0-9_-' '_')"
}
announced() { grep -qxF "$1" "$(state_file)" 2>/dev/null; }
mark_announced() { printf '%s\n' "$1" >> "$(state_file)"; }

context_for() {
  local root=$1 mode=jj ver
  [ -d "$root/.git" ] && mode=jj-colocated
  ver=$(jj --version 2>/dev/null | awk '{print $2}' | cut -d- -f1)
  printf 'vcs=%s at %s (jj %s). This directory is a Jujutsu repository: use the jj skill for every version-control action in it. Do not run git commands that change state there: they are blocked where possible, and any git change is reported with a recovery point. Read-only git still works, but prefer jj.' \
    "$mode" "$root" "${ver:-not found on PATH}"
}

# --- Detecting git changes around a Bash command (pre-tool.sh records, post-tool.sh checks) ---

# Baseline file for one tool call, keyed by tool_use_id so parallel calls don't collide.
baseline_file() {
  printf '%s/baselines/%s' "${CLAUDE_PLUGIN_DATA:-${TMPDIR:-/tmp}/jj-agent}" \
    "$(printf '%s' "${1:-${SESSION_ID:-default}}" | tr -c 'A-Za-z0-9_-' '_')"
}

# Content hash of the colocated git index (empty if none). jj snapshots only touch its mtime;
# git commands that rewrite working-copy files (checkout --, restore, stash, reset) change its content.
index_hash() { [ -f "$1/.git/index" ] && cksum < "$1/.git/index" | awk '{print $1 "-" $2}'; }

current_op() { (cd "$1" && jj op log --ignore-working-copy --no-graph -n 1 -T 'id' 2>/dev/null); }

# First-line descriptions of the operations after op $2 in repo $1, newest first.
# Prints nothing if $2 is not among the last 50 operations.
ops_since() {
  (cd "$1" && jj op log --ignore-working-copy --no-graph -n 50 \
    -T 'id ++ "\t" ++ description.first_line() ++ "\n"' 2>/dev/null) |
    awk -F'\t' -v b="$2" '$1 == b { for (i = 1; i <= n; i++) print a[i]; exit } { a[++n] = $2 }'
}

# Does the command text run a git subcommand that changes state?
git_writes_in() {
  printf '%s' "$1" | grep -Eq '(^|[^[:alnum:]_./-])git([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+(add|am|apply|checkout|cherry-pick|clean|commit|merge|mv|pull|rebase|reset|restore|revert|rm|stash|switch)([^[:alnum:]-]|$)'
}

# Print a report if git changed repo $1 between baseline op $2 (index hash $3) and now (index hash
# $4, read before any jj command ran). $5 is the command text. Call after snapshotting.
git_report() {
  local root=$1 op=$2 idx0=$3 idx1=$4 cmd=$5 ops why='' short
  [ -n "$op" ] || return 0
  ops=$(ops_since "$root" "$op")
  [ -n "$ops" ] || return 0
  if printf '%s\n' "$ops" | grep -q '^import git '; then
    why='git moved HEAD or refs'
  elif [ -n "$idx0" ] && [ "$idx0" != "$idx1" ] &&
    ! printf '%s\n' "$ops" | grep -qv '^snapshot working copy$'; then
    # Only snapshots in between, so no jj command of the agent's rewrote the index: git did.
    why='git rewrote working-copy files (the git index changed)'
  elif git_writes_in "$cmd" && printf '%s\n' "$ops" | grep -q '^snapshot working copy$'; then
    why='the command ran git and files changed'
  fi
  [ -n "$why" ] || return 0
  short=$(printf '%s' "$op" | cut -c1-12)
  printf 'jj-agent: %s in %s during the last command. The repo state from just before it is jj operation %s. Check what happened with `jj op log -n 5` and `jj op show <op-id>`. If it was not intended: `jj op restore %s` returns the whole repo to that state (this also undoes everything else the command did), or `jj restore --from '"'"'at_operation(%s, @)'"'"' <paths>` restores single files. Use jj instead of git in this repo (jj skill).' \
    "$why" "$root" "$short" "$short" "$short"
}

# Emit additionalContext for hook event $1 with text $2.
emit_context() {
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$1" "$(json_str "$2")"
}

# For each directory argument: find its jj root, and collect a context message for roots not yet announced.
# Sets NEW_CONTEXT and JJ_ROOTS (newline-separated, unique).
scan_dirs() {
  local d r
  NEW_CONTEXT='' JJ_ROOTS=''
  for d in "$@"; do
    r=$(find_jj_root "$d") || continue
    case "
$JJ_ROOTS
" in *"
$r
"*) continue ;; esac
    JJ_ROOTS="${JJ_ROOTS:+$JJ_ROOTS
}$r"
    if ! announced "$r"; then
      mark_announced "$r"
      NEW_CONTEXT="${NEW_CONTEXT:+$NEW_CONTEXT }$(context_for "$r")"
    fi
  done
}
