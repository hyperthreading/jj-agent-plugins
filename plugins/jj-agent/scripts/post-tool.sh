#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit|NotebookEdit|Bash)
# Only acts inside jj repos; elsewhere it exits after a directory walk.
# - Snapshot the jj working copy so every agent step lands in `jj op log`.
# - If this step is the first time Claude touches a jj repo in this session (e.g. it just ran
#   `jj git init`, or cd'd into a jj repo), tell Claude next to the tool result.
HOOK_INPUT=$(cat)
. "$(dirname "$0")/lib.sh"

file=$(json_get file_path); [ -n "$file" ] || file=$(json_get notebook_path)
cwd=$(json_get cwd)
fdir=; [ -n "$file" ] && fdir=$(dirname "$file")

# Cheap exit before anything else when no candidate is inside a jj repo.
find_jj_root "$fdir" >/dev/null || find_jj_root "${cwd:-$PWD}" >/dev/null || exit 0

SESSION_ID=$(json_get session_id)
scan_dirs "$fdir" "${cwd:-$PWD}"

if command -v jj >/dev/null 2>&1; then
  printf '%s\n' "$JJ_ROOTS" | while IFS= read -r r; do
    [ -n "$r" ] || continue
    (cd "$r" && { jj util snapshot >/dev/null 2>&1 || jj st >/dev/null 2>&1; })
  done
fi

[ -n "$NEW_CONTEXT" ] && emit_context PostToolUse "$NEW_CONTEXT"
exit 0
