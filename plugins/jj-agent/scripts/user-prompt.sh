#!/usr/bin/env bash
# UserPromptSubmit
# Catches repos that became jj between turns (e.g. the user ran `jj git init` in their own
# terminal): tell Claude once, alongside the prompt. Silent outside jj repos.
. "${BASH_SOURCE%/*}/lib.sh"
read_input
json_get cwd cwd; cwd=${cwd:-$PWD}
find_jj_root "$cwd" || exit 0
json_get session_id SESSION_ID
scan_dirs "$cwd"
[ -n "$NEW_CONTEXT" ] && emit_context UserPromptSubmit "$NEW_CONTEXT"
exit 0
