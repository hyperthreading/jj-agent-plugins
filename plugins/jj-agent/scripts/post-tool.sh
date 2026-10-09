#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit|NotebookEdit|Bash; Codex matches apply_patch as Edit/Write)
# Only acts inside jj repos; elsewhere it exits after a directory walk.
# - Snapshot the jj working copy so every agent step lands in `jj op log`.
# - After a Bash command that pre-tool.sh recorded a baseline for: if git changed the repo during
#   the command, tell Claude what happened and which operation to restore.
# - If this step is the first time Claude touches a jj repo in this session (e.g. it just ran
#   `jj git init`, or cd'd into a jj repo), tell Claude next to the tool result.
. "${BASH_SOURCE%/*}/lib.sh"
read_input

json_get file_path file; [ -n "$file" ] || json_get notebook_path file
json_get cwd cwd; cwd=${cwd:-$PWD}
fdir=; [ -n "$file" ] && fdir=${file%/*}

# Cheap exit when no candidate is inside a jj repo. pre-tool.sh only records a baseline inside one.
find_jj_root "$fdir" || find_jj_root "$cwd" || exit 0

json_get session_id SESSION_ID
json_get tool_use_id id
baseline_path "$id"
broot= bop=
if [ -f "$BF" ]; then
  { IFS= read -r broot; IFS= read -r bop; } < "$BF"
  # If the git index changed, copy it before any jj command below can rewrite it.
  if [ -f "$BF.index" ] && ! cmp -s "$BF.index" "$broot/.git/index" 2>/dev/null; then
    save_index "$broot" "$BF.post"
  fi
fi

scan_dirs "$fdir" "$cwd" ${broot:+"$broot"}

REPORT=
if command -v jj >/dev/null 2>&1; then
  for r in "${JJ_ROOTS[@]}"; do
    if [ "$r" = "$broot" ] && [ -n "$bop" ]; then
      git_report "$broot" "$bop" "$BF.index" "$BF.post"   # snapshots as part of it
    else
      jj -R "$r" util snapshot >/dev/null 2>&1
    fi
  done
fi

[ -n "$broot" ] && rm -f "$BF" "$BF.index" "$BF.post"

msg="$NEW_CONTEXT${NEW_CONTEXT:+${REPORT:+ }}$REPORT"
[ -n "$msg" ] && emit_context PostToolUse "$msg"
exit 0
