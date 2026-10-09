#!/usr/bin/env bash
# PreToolUse (Bash)
# Only acts inside jj repos; elsewhere it exits after a directory walk.
# Record a baseline (the latest operation and a copy of the git index) for post-tool.sh to detect git
# changes the command makes. No snapshot here: the previous tool call's PostToolUse and this turn's
# UserPromptSubmit already took one, so the latest operation is the state the command starts from
# (only edits made by others in the middle of a turn are missed). Skipping it saves a working-copy
# scan, which grows with the number of files.
# Never blocks or rewrites the command: Codex has no way to put the git shim on PATH, so detection
# after the fact is the guard there (and a backstop behind the shim in Claude Code).
. "${BASH_SOURCE%/*}/lib.sh"
read_input

json_get cwd cwd
find_jj_root "${cwd:-$PWD}" || exit 0
root=$JJ_ROOT
command -v jj >/dev/null 2>&1 || exit 0

json_get session_id SESSION_ID
json_get tool_use_id id
baseline_path "$id"
op=$(jj -R "$root" op log --ignore-working-copy --no-graph -n 1 -T id 2>/dev/null)
[ -n "$op" ] || exit 0
[ -d "${BF%/*}" ] || mkdir -p "${BF%/*}" 2>/dev/null
save_index "$root" "$BF.index" || rm -f "$BF.index"
printf '%s\n%s\n' "$root" "$op" > "$BF"
exit 0
