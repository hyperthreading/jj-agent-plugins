#!/usr/bin/env bash
# PreToolUse (Bash)
# Only acts inside jj repos; elsewhere it exits after a directory walk.
# Snapshot right before the command, so `jj op log` holds the state it started from, and record a
# baseline (operation id, git index hash) for post-tool.sh to detect git changes the command makes.
# Never blocks or rewrites the command: Codex has no way to put the git shim on PATH, so detection
# after the fact is the guard there (and a backstop behind the shim in Claude Code).
HOOK_INPUT=$(cat)
. "$(dirname "$0")/lib.sh"

cwd=$(json_get cwd)
root=$(find_jj_root "${cwd:-$PWD}") || exit 0
command -v jj >/dev/null 2>&1 || exit 0

SESSION_ID=$(json_get session_id)
(cd "$root" && { jj util snapshot >/dev/null 2>&1 || jj st >/dev/null 2>&1; })
op=$(current_op "$root")
[ -n "$op" ] || exit 0
bf=$(baseline_file "$(json_get tool_use_id)")
mkdir -p "$(dirname "$bf")" 2>/dev/null
printf '%s\n%s\n%s\n' "$root" "$op" "$(index_hash "$root")" > "$bf"
exit 0
