#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit|NotebookEdit|Bash; Codex matches apply_patch as Edit/Write), and
# PostToolUseFailure (Bash): Claude Code skips PostToolUse when a command exits non-zero.
# Only acts inside jj repos; elsewhere it exits after a directory walk.
# - Snapshot the jj working copy so every agent step lands in `jj op log`.
# - After a Bash command that pre-tool.sh recorded a baseline for: if git changed the repo during
#   the command, tell Claude what happened and which operation to restore.
# - If this step is the first time Claude touches a jj repo in this session (e.g. it just ran
#   `jj git init`, or cd'd into a jj repo), tell Claude next to the tool result.
# Claude Code and Codex get the message as additionalContext. Muse Code gets it inside a tool result
# (docs/adr/0002-muse-code-support.md): exit-2 feedback that repeats the original result first, or,
# for a failed command or a result too big to repeat, the next state-changing call that pre-tool.sh
# holds.
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
  if [ -f "$BF.index" ] && git_index_path "$broot" && ! cmp -s "$BF.index" "$GI" 2>/dev/null; then
    save_index "$broot" "$BF.post"
  fi
fi

scan_dirs "$fdir" "$cwd" ${broot:+"$broot"}

read_command
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
[ -n "$msg" ] || exit 0
json_get hook_event_name event
# Muse Code merges additionalContext into its first developer message, where the model misses it or
# takes it for something from before the session. Hand the message back after the original result
# instead; the next state-changing call is held once all the same, so that a call queued together
# with this one cannot run before the model has looked.
if [ -n "$MUSE_PLUGIN_ID" ]; then
  if [ "$event" != PostToolUseFailure ]; then
    json_get tool_response orig
    out="$orig${orig:+$'\n\n'}$msg"
    if fits_hook_stream "$out"; then
      printf '%s\n' "$out" >&2
      [ -n "$REPORT" ] && save_pending delivered "$CMD"
      exit 2
    fi
  fi
  # A failed call's result cannot be replaced, and an oversized one must not be: Muse kills a hook
  # whose output passes 16 KiB. The next state-changing call carries the notice.
  if [ -n "$REPORT" ]; then
    save_pending undelivered "${msg/ that you just ran in / that you ran earlier in }"
    exit 0
  fi
fi
emit_context "${event:-PostToolUse}" "$msg"
exit 0
