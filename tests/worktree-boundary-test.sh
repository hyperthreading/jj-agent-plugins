#!/usr/bin/env bash
# Regression tests for scoped worktree adoption and submodule boundaries. Needs bash, jj, git, Python 3.
set -eu
here=$(cd "$(dirname "$0")" && pwd -P)
P=$(cd "${1:-$here/../plugins/jj-agent/scripts}" && pwd -P)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/jj-boundary-test.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
export JJ_SHIM_OFF=1
HB=${HOOK_BASH:-/bin/bash}
main="$tmp/main repo" external="$tmp/user hotfix"
nested="$main/.claude/worktrees/nested"
submodule="$main/submodule"
mkdir -p "$main" "$tmp/source" "$tmp/no-jj"
jj git init "$main" >/dev/null 2>&1
printf 'base\n' > "$main/f"
jj -R "$main" commit -m base >/dev/null 2>&1
git -C "$main" worktree add -q -b hotfix "$external"
git -C "$main" worktree add -q -b nested "$nested"
git -C "$tmp/source" init -q
git -C "$tmp/source" -c user.name=Test -c user.email=test@example.com commit -qm base --allow-empty
git -C "$main" -c protocol.file.allow=always submodule add -q "$tmp/source" submodule
# A relative gitdir without a final newline is valid Git input and still a boundary.
printf 'gitdir: ../../../.git/worktrees/nested' > "$nested/.git"
git -C "$nested" rev-parse --git-dir >/dev/null
printf '.env\n.claude/\n' >> "$main/.git/info/exclude"

hook() { # event script cwd [file path]
  printf '{"session_id":"boundary","tool_use_id":"boundary","hook_event_name":"%s","cwd":"%s","tool_name":"Bash","tool_input":{"command":"true","file_path":"%s"}}' "$1" "$3" "${4:-}" |
    CLAUDE_PLUGIN_DATA="$tmp/state" "$HB" "$P/$2.sh"
}
all_hooks() {
  hook SessionStart session-start "$1"
  hook UserPromptSubmit user-prompt "$1"
  hook PreToolUse pre-tool "$1"
  hook PostToolUse post-tool "$1"
  hook PostToolUseFailure post-tool "$1"
  # File tools can pass a path inside the boundary while cwd is outside every jj repo.
  printf '{"session_id":"boundary","hook_event_name":"PostToolUse","cwd":"%s","tool_name":"Write","tool_input":{"file_path":"%s/f"}}' "$tmp" "$1" |
    CLAUDE_PLUGIN_DATA="$tmp/state" "$HB" "$P/post-tool.sh"
}

# Preserve content, mode, mtime, inode, branch and Git admin registration, not just filenames.
for wt in "$external" "$nested" "$submodule"; do
  printf 'dirty\n' > "$wt/f"
  printf 'ignored\n' > "$wt/.env"
  printf 'untracked\n' > "$wt/local"
  chmod 751 "$wt/f"
  touch -t 202001020304 "$wt/f" "$wt/.env" "$wt/local"
  name=${wt##*/}
  mkdir "$tmp/saved-$name"
  cp -p "$wt/f" "$wt/.env" "$wt/local" "$wt/.git" "$tmp/saved-$name/"
  ls -di "$wt" "$wt/f" "$wt/.env" "$wt/local" > "$tmp/inodes-$name"
  git -C "$wt" rev-parse HEAD > "$tmp/head-$name"
done

# Hooks in the parent must not sweep any user's existing worktree.
all_hooks "$main" >/dev/null
[ ! -e "$external/.jj" ] && [ ! -e "$nested/.jj" ]
printf '  ok    parent hooks leave unrelated worktrees untouched\n'
before=$(jj -R "$main" op log --ignore-working-copy --no-graph -n 1 -T id)
rm -rf "$tmp/state"
cat > "$tmp/no-jj/jj" <<'EOF'
#!/bin/sh
printf 'unexpected jj call\n' >> "$JJ_BOUNDARY_CALLS"
exit 99
EOF
chmod +x "$tmp/no-jj/jj"
export JJ_BOUNDARY_CALLS="$tmp/jj-calls"
for wt in "$external" "$nested" "$submodule"; do
  mkdir -p "$wt/deep/child"
  if [ "$wt" = "$submodule" ]; then
    out=$(PATH="$tmp/no-jj:$PATH" all_hooks "$wt/deep/child" 2>&1)
    [ -z "$out" ] && [ ! -e "$wt/.jj" ]
  else
    out=$(all_hooks "$wt/deep/child" 2>&1)
    case $out in *"Initialized Git worktree"*"jj operation history is local"*) ;; *) printf 'Missing adoption notice: %s\n' "$out"; exit 1 ;; esac
    [ -d "$wt/.jj/repo" ] && [ ! -e "$wt/.jj/jj-agent-wt" ]
    again=$(all_hooks "$wt/deep/child" 2>&1)
    case $again in *"Initialized Git worktree"*) exit 1 ;; esac
  fi
  name=${wt##*/}
  for file in f .env local .git; do
    cmp "$wt/$file" "$tmp/saved-$name/$file"
    [ ! "$wt/$file" -nt "$tmp/saved-$name/$file" ]
    [ ! "$tmp/saved-$name/$file" -nt "$wt/$file" ]
  done
  [ -x "$wt/f" ]
  ls -di "$wt" "$wt/f" "$wt/.env" "$wt/local" > "$tmp/after-$name"
  cmp "$tmp/inodes-$name" "$tmp/after-$name"
  [ "$(git -C "$wt" rev-parse HEAD)" = "$(cat "$tmp/head-$name")" ]
  git -C "$wt" status --porcelain >/dev/null
  printf '  ok    %s: scoped hooks preserve files and Git registration\n' "$name"

  # Submodules stay raw; an adopted worktree now has its own jj guard.
  if [ "$wt" = "$submodule" ]; then
    (cd "$main" && PATH="$P/shim:$PATH" JJ_SHIM_OFF= git -C "$wt/deep/child" add "$wt/local")
    git -C "$wt" diff --cached --name-only | grep -qx local
  else
    if (cd "$main" && PATH="$P/shim:$PATH" JJ_SHIM_OFF= git -C "$wt/deep/child" add "$wt/local") >"$tmp/blocked" 2>&1; then exit 1; fi
    grep -q 'Blocked: this is a jj' "$tmp/blocked"
  fi
  printf '  ok    %s: shim uses the checkout boundary\n' "$name"
done
[ ! -e "$JJ_BOUNDARY_CALLS" ]
[ "$(jj -R "$main" op log --ignore-working-copy --no-graph -n 1 -T id)" = "$before" ]
printf '  ok    adoption keeps jj operation history separate from the parent\n'

# Invalid .git files must also stop the walk; no content parsing is needed to find the boundary.
mkdir "$main/invalid"
printf 'not a gitdir' > "$main/invalid/.git"
out=$(PATH="$tmp/no-jj:$PATH" all_hooks "$main/invalid" 2>&1)
[ -z "$out" ] && [ ! -e "$JJ_BOUNDARY_CALLS" ]
printf '  ok    malformed .git file is still a boundary\n'

# Existing explicit jj workspaces take precedence over the .git-file boundary.
jj -R "$main" workspace add --colocate --name explicit "$tmp/explicit" >/dev/null 2>&1
out=$(hook SessionStart session-start "$tmp/explicit")
case $out in *vcs=jj-colocated*) ;; *) printf 'Missing jj context: %s\n' "$out"; exit 1 ;; esac
if (cd "$tmp/explicit" && PATH="$P/shim:$PATH" JJ_SHIM_OFF= git add f) >"$tmp/blocked" 2>&1; then
  printf 'shim allowed a Git write in an explicit jj workspace\n'; exit 1
fi
grep -q 'Blocked: this is a jj' "$tmp/blocked"
printf '  ok    explicit jj workspace is announced and guarded\n'

# Adopted Git worktrees can still be removed by their owning harness; no jj workspace was registered.
git -C "$main" worktree remove --force "$external"
git -C "$main" worktree remove --force "$nested"
names=$(jj -R "$main" workspace list --ignore-working-copy -T 'name ++ "\n"')
[ "$names" = "$(printf 'default\nexplicit')" ]
printf '  ok    Git cleanup leaves no plugin-created jj workspaces\n'

# A clean adopted worktree needs no --force: jj's metadata is ignored by Git.
git -C "$main" worktree add -q --detach "$tmp/clean"
hook SessionStart session-start "$tmp/clean" >/dev/null
git -C "$main" worktree remove "$tmp/clean"
printf '  ok    a clean adopted worktree supports ordinary Git harness cleanup\n'

# PreToolUse can be the first hook: initialize and announce before recording the command baseline.
git -C "$main" worktree add -q --detach "$tmp/pre-first"
out=$(hook PreToolUse pre-tool "$tmp/pre-first")
case $out in *'"hookEventName":"PreToolUse"'*'Initialized Git worktree'*vcs=jj-colocated*) ;; *) exit 1 ;; esac
out=$(hook PostToolUse post-tool "$tmp/pre-first")
[ -z "$out" ]
printf '  ok    first PreToolUse announces initialization before the command, once\n'

# Muse must receive first-touch context beside the result, not lose it in PreToolUse.
git -C "$main" worktree add -q --detach "$tmp/muse-pre-first"
out=$(MUSE_PLUGIN_ID=test hook PreToolUse pre-tool "$tmp/muse-pre-first")
[ -z "$out" ]
rc=0
out=$(MUSE_PLUGIN_ID=test hook PostToolUse post-tool "$tmp/muse-pre-first" 2>&1) || rc=$?
[ "$rc" = 2 ]
case $out in *'Initialized Git worktree'*'jj operation history is local'*vcs=jj-colocated*) ;; *) exit 1 ;; esac
out=$(MUSE_PLUGIN_ID=test hook PostToolUse post-tool "$tmp/muse-pre-first" 2>&1)
[ -z "$out" ]
printf '  ok    Muse first PreToolUse delivers initialization at PostToolUse, once\n'

# A failed tool has no replaceable result: retain the notice for the next call.
git -C "$main" worktree add -q --detach "$tmp/muse-pre-failed"
out=$(MUSE_PLUGIN_ID=test hook PreToolUse pre-tool "$tmp/muse-pre-failed")
[ -z "$out" ]
out=$(MUSE_PLUGIN_ID=test hook PostToolUseFailure post-tool "$tmp/muse-pre-failed" 2>&1)
[ -z "$out" ]
out=$(MUSE_PLUGIN_ID=test hook PreToolUse pre-tool "$tmp/muse-pre-failed")
case $out in *'"permissionDecision":"deny"'*'Initialized Git worktree'*'jj operation history is local'*) ;; *) exit 1 ;; esac
printf '  ok    Muse retains initialization context when the first tool fails\n'
