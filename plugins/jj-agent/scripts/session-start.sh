#!/usr/bin/env bash
# SessionStart (startup, resume, clear, compact)
# - Put the git shim first on PATH for this session's Bash commands. The shim passes everything
#   straight to git unless the directory is inside a jj repo, so it is inert elsewhere and starts
#   guarding the moment a repo becomes jj, even mid-session. (Plugin bin/ dirs come after the
#   user's PATH and can't shadow git, so CLAUDE_ENV_FILE is used to prepend.) Harnesses without
#   CLAUDE_ENV_FILE (Codex) get no shim; post-tool.sh detects git changes there instead.
# - Reset which repos Claude has been told about (context may have been cleared or compacted).
# - If the session starts inside a jj repo, tell Claude now. Otherwise stay silent.
HOOK_INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
SESSION_ID=$(json_get session_id)

# Next to this script, so it is found both as a Claude plugin and when installed by APM.
shim="$(cd "$(dirname "$0")" && pwd -P)/shim"
[ -x "$shim/git" ] || chmod +x "$shim/git" 2>/dev/null
if [ -n "$CLAUDE_ENV_FILE" ] && [ -x "$shim/git" ]; then
  q=$(printf '%q' "$shim")
  printf 'case ":$PATH:" in *:%s:*) ;; *) export PATH=%s:"$PATH" ;; esac\n' "$q" "$q" >> "$CLAUDE_ENV_FILE"
fi

sf=$(state_file); : > "$sf"
find "$(dirname "$sf")" -type f -mtime +14 -exec rm -f {} + 2>/dev/null
# Baselines left behind by Bash calls whose PostToolUse never ran (interrupted, denied).
find "$(dirname "$(baseline_file x)")" -type f -mtime +1 -exec rm -f {} + 2>/dev/null

cwd=$(json_get cwd)
scan_dirs "${cwd:-${CLAUDE_PROJECT_DIR:-$PWD}}"
[ -n "$NEW_CONTEXT" ] && emit_context SessionStart "$NEW_CONTEXT"
exit 0
