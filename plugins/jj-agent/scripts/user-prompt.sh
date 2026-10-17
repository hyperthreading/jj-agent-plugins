#!/usr/bin/env bash
# UserPromptSubmit
# - Snapshot, so edits (and git commands) the user made between turns are recorded before the agent
#   acts, and are neither lost nor attributed to the agent's next command (see pre-tool.sh).
# - Catch repos that became jj between turns (e.g. the user ran `jj git init` in their own
#   terminal): tell Claude once, alongside the prompt. Silent outside jj repos.
. "${BASH_SOURCE%/*}/lib.sh"
read_input
json_get cwd cwd; cwd=${cwd:-$PWD}
find_jj_root "$cwd" || exit 0
json_get session_id SESSION_ID
scan_dirs "$cwd"
step_args 'changes made between turns'
if command -v jj >/dev/null 2>&1; then
  adopt_new_worktrees "$JJ_ROOT"
  snapshot "$JJ_ROOT"
fi
[ -n "$NEW_CONTEXT" ] && emit_context UserPromptSubmit "$NEW_CONTEXT"
exit 0
