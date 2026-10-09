#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit|NotebookEdit|Bash; Codex matches apply_patch as Edit/Write)
# Only acts inside jj repos; elsewhere it exits after a directory walk.
# - Snapshot the jj working copy so every agent step lands in `jj op log`.
# - After a Bash command that pre-tool.sh recorded a baseline for: if git changed the repo during
#   the command, tell Claude what happened and which operation to restore.
# - If this step is the first time Claude touches a jj repo in this session (e.g. it just ran
#   `jj git init`, or cd'd into a jj repo), tell Claude next to the tool result.
HOOK_INPUT=$(cat)
. "$(dirname "$0")/lib.sh"

file=$(json_get file_path); [ -n "$file" ] || file=$(json_get notebook_path)
cwd=$(json_get cwd)
fdir=; [ -n "$file" ] && fdir=$(dirname "$file")
SESSION_ID=$(json_get session_id)

# Read the baseline and the git index before any jj command below can touch them.
bf=$(baseline_file "$(json_get tool_use_id)")
broot= bop= bidx= idx_now=
if [ -f "$bf" ]; then
  { IFS= read -r broot; IFS= read -r bop; IFS= read -r bidx; } < "$bf"
  rm -f "$bf"
  idx_now=$(index_hash "$broot")
fi

# Cheap exit before anything else when no candidate is inside a jj repo.
[ -n "$broot" ] || find_jj_root "$fdir" >/dev/null || find_jj_root "${cwd:-$PWD}" >/dev/null || exit 0

scan_dirs "$fdir" "${cwd:-$PWD}" ${broot:+"$broot"}

report=
if command -v jj >/dev/null 2>&1; then
  printf '%s\n' "$JJ_ROOTS" | while IFS= read -r r; do
    [ -n "$r" ] || continue
    (cd "$r" && { jj util snapshot >/dev/null 2>&1 || jj st >/dev/null 2>&1; })
  done
  [ -n "$broot" ] && report=$(git_report "$broot" "$bop" "$bidx" "$idx_now" "$(tool_input_get command)")
fi

msg="$NEW_CONTEXT${NEW_CONTEXT:+${report:+ }}$report"
[ -n "$msg" ] && emit_context PostToolUse "$msg"
exit 0
