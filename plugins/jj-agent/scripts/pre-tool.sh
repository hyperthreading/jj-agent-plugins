#!/usr/bin/env bash
# PreToolUse (Bash, and the state-changing file tools: Edit|Write|MultiEdit|NotebookEdit)
# Only acts inside jj repos; elsewhere it exits after a directory walk.
# Record a baseline (the latest operation and a copy of the git index) for post-tool.sh to detect git
# changes a shell command makes. No snapshot here: the previous tool call's PostToolUse and this turn's
# UserPromptSubmit already took one, so the latest operation is the state the command starts from
# (only edits made by others in the middle of a turn are missed). Skipping it saves a working-copy
# scan, which grows with the number of files.
# Never rewrites the command. Codex has no way to put the git shim on PATH, so detection after the
# fact is the guard there (and a backstop behind the shim in Claude Code).
# Muse Code only: if post-tool.sh held a git-change notice for this session, deny this one call and
# hand the notice over as its result (docs/adr/0002-muse-code-support.md).
. "${BASH_SOURCE%/*}/lib.sh"
read_input

json_get tool_name tool
# File tools only reach this hook for the Muse hold below; Muse names its own shell tool "bash".
case $tool in *[Ee]dit*|*[Ww]rite*|*[Pp]atch*) shell= ;; *) shell=1 ;; esac
json_get session_id SESSION_ID

if [ -n "$MUSE_PLUGIN_ID" ]; then
  pending_path
  if [ -f "$PF" ]; then
    state= body=
    { IFS= read -r state; IFS= read -r -d '' body; } < "$PF"
    rm -f "$PF"
    body=${body%$'\n'}
    read_command
    lead=${CMD%%[![:space:]]*}
    case ${CMD#"$lead"} in
      jj|jj[[:space:]]*) [ "$state" = delivered ] && [ -n "$shell" ] && hold= || hold=1 ;;
      *) hold=1 ;;
    esac
    if [ -n "$hold" ]; then
      [ ${#body} -gt 4000 ] && body="${body:0:4000} ..."
      if [ "$state" = delivered ]; then
        reason="jj-agent held this call, so it did not run: the result of \`${body:-the previous command}\` reports that git changed this repo."
      else
        reason="jj-agent held this call, so it did not run. $body"
      fi
      json_str reason "$reason Look into that first, then run this call again if it is still needed."
      printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$reason"
      exit 0
    fi
  fi
fi

[ -n "$shell" ] || exit 0
json_get cwd cwd
find_jj_root "${cwd:-$PWD}" || exit 0
root=$JJ_ROOT
command -v jj >/dev/null 2>&1 || exit 0

json_get tool_use_id id
baseline_path "$id"
op=$(jj -R "$root" op log --ignore-working-copy --no-graph -n 1 -T id 2>/dev/null)
[ -n "$op" ] || exit 0
[ -d "${BF%/*}" ] || mkdir -p "${BF%/*}" 2>/dev/null
save_index "$root" "$BF.index" || rm -f "$BF.index"
printf '%s\n%s\n' "$root" "$op" > "$BF"
exit 0
