#!/usr/bin/env bash
# UserPromptSubmit
# Catches repos that became jj between turns (e.g. the user ran `jj git init` in their own
# terminal): tell Claude once, alongside the prompt. Silent outside jj repos.
HOOK_INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
cwd=$(json_get cwd)
find_jj_root "${cwd:-$PWD}" >/dev/null || exit 0
SESSION_ID=$(json_get session_id)
scan_dirs "${cwd:-$PWD}"
[ -n "$NEW_CONTEXT" ] && emit_context UserPromptSubmit "$NEW_CONTEXT"
exit 0
