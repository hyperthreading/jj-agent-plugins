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
  printf 'vcs=%s at %s (jj %s). This directory is a Jujutsu repository: use the jj-agent:jj skill for every version-control action in it. git commands that change state are blocked there; read-only git still works, but prefer jj.' \
    "$mode" "$root" "${ver:-not found on PATH}"
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
