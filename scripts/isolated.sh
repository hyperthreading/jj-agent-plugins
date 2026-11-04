#!/usr/bin/env bash
# Run checks with private client/jj state; preserve PATH so installed tools stay available.
set -eu
stage=$(mktemp -d "${TMPDIR:-/tmp}/jj-guidance-env.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
for name in $(compgen -v); do
  case $name in OPENCODE_*|CLAUDE_*|CODEX_*|MUSE_*|JJ_AGENT_*) unset "$name" ;; esac
done
export HOME="$stage/home" TMPDIR="$stage"
export XDG_CONFIG_HOME="$HOME/config" XDG_DATA_HOME="$HOME/data" XDG_CACHE_HOME="$HOME/cache" XDG_STATE_HOME="$HOME/state"
export OPENCODE_CONFIG_DIR="$XDG_CONFIG_HOME/opencode" CODEX_HOME="$HOME/codex"
export JJ_CONFIG="$stage/jj.toml" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME='Guidance checks' GIT_AUTHOR_EMAIL=guidance@example.invalid
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
mkdir -p "$HOME" "$OPENCODE_CONFIG_DIR" "$CODEX_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME"
printf 'user.name="Guidance checks"\nuser.email="guidance@example.invalid"\n' > "$JJ_CONFIG"
"$@"
