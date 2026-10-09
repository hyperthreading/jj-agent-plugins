#!/usr/bin/env bash
# Scenario tests for the jj-agent hooks. Each scenario runs a command between the PreToolUse and
# PostToolUse hooks, the way Claude Code and Codex call them for a Bash tool call, and checks the
# git-change report. Every scenario runs twice: with the full PATH and with a minimal one (no jq,
# no git shim). Hooks run under /bin/bash when it exists, like the hooks.json commands.
#
# usage: tests/hooks-test.sh [plugin-scripts-dir]   (default: plugins/jj-agent/scripts)
# needs: bash, jj, git
set -u

here=$(cd "$(dirname "$0")" && pwd -P)
P=$(cd "${1:-$here/../plugins/jj-agent/scripts}" && pwd -P) || exit 2
export JJ_SHIM_OFF=1   # scenarios run git directly; this only matters when a git shim is on PATH
# Drop installed jj-agent shims from PATH: the tests must not depend on the session's plugin copy.
is_shim() { local l1 l2; { IFS= read -r l1; IFS= read -r l2; } < "$1" 2>/dev/null; case $l2 in "# git shim for Claude Code sessions"*) return 0 ;; esac; return 1; }
clean_path=
IFS=: read -r -a _dirs <<< "$PATH"
for _d in "${_dirs[@]}"; do [ -x "$_d/git" ] && is_shim "$_d/git" && continue; clean_path=${clean_path:+$clean_path:}$_d; done
export PATH=$clean_path

tmp=$(mktemp -d "${TMPDIR:-/tmp}/jj-agent-test.XXXXXX") || exit 2
trap '[ -n "$tmp" ] && rm -rf -- "$tmp"' EXIT

pass=0 fail=0
HB=bash; [ -x /bin/bash ] && HB=/bin/bash   # interpreter, as in hooks.json
ok()  { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL  %s\n        %s\n' "$1" "$2"; }

json_esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
hook_input() { # event cwd tool_use_id tool_name command
  printf '{"session_id":"test","cwd":"%s","hook_event_name":"%s","tool_name":"%s","tool_use_id":"%s","tool_input":{"command":"%s"}}' \
    "$(json_esc "$2")" "$1" "$4" "$3" "$(json_esc "$5")"
}

# A minimal PATH without jq or any git shim: the hooks must not depend on either.
make_nojq_path() {
  local d=$tmp/nojq-bin t p dir
  mkdir -p "$d"
  for t in bash sh jj awk sed grep cut tr cksum dirname cat mkdir printf ls wc chmod head find rm ps basename env cp cmp; do
    p=$(type -P "$t") && ln -sf "$p" "$d/$t"
  done
  # real git: the first git on PATH that is not a shim
  local IFS=:
  for dir in $PATH; do
    if [ -x "$dir/git" ] && ! is_shim "$dir/git"; then ln -sf "$dir/git" "$d/git"; break; fi
  done
  printf '%s' "$d"
}

# Run one tool call against $repo: pre hook (Bash only), the command, post hook. Sets OUT to the
# additionalContext text (empty if none). post_event is PostToolUseFailure for a failed command.
call() { # command [tool_name] [post_event]
  local cmd=$1 tn=${2:-Bash} ev=${3:-PostToolUse} out
  n=$((n + 1))
  if [ "$tn" = Bash ]; then
    hook_input PreToolUse "$repo" "tu$n" "$tn" "$cmd" | PATH=$hook_path $HB "$P/pre-tool.sh"
  fi
  (cd "$repo" && eval "$cmd") >/dev/null 2>&1
  out=$(hook_input "$ev" "$repo" "tu$n" "$tn" "$cmd" | PATH=$hook_path $HB "$P/post-tool.sh")
  RAW=$out
  OUT=$(printf '%s' "$out" | sed -n 's/.*"additionalContext":"\(.*\)"}}$/\1/p')
}

# The user edits files between turns; UserPromptSubmit runs when they send the next prompt.
user_turn() { # shell snippet run in $repo
  (cd "$repo" && eval "$1") >/dev/null 2>&1
  hook_input UserPromptSubmit "$repo" x x x | PATH=$hook_path $HB "$P/user-prompt.sh" >/dev/null
}

reason() { printf '%s' "$OUT" | sed -n 's/.*jj-agent: during the last command in [^,]*, \(.*\)\. The repo state.*/\1/p'; }

expect() { # name expected-reason ('' = no report)
  local got; got=$(reason)
  if [ "$got" = "$2" ]; then ok "$1"; else bad "$1" "expected [${2:-no report}], got [${got:-no report}]"; fi
}

run_suite() { # label hook-PATH
  local label=$1 r op
  hook_path=$2 n=0
  export CLAUDE_PLUGIN_DATA=$tmp/$label/data
  repo="$tmp/$label/my repo"   # a space in the path on purpose
  mkdir -p "$repo" "$tmp/$label/plain"
  (
    cd "$repo" && jj git init >/dev/null 2>&1 &&
      echo a > f && echo b > g && echo c > h &&
      printf '#!/bin/sh\ngit checkout -- f\n' > reset-f.sh && chmod +x reset-f.sh &&
      jj commit -m base >/dev/null 2>&1
  ) || { bad "$label: setup" "could not create a jj repo"; return; }
  echo "== $label"

  call "true"
  case $OUT in *"vcs=jj-colocated"*) ok "first touch announces the jj repo" ;; *) bad "first touch announces the jj repo" "got [$OUT]" ;; esac

  call "echo x >> f";                                   expect "plain edit" ""
  call "git add -A && git commit -qm viagit";           expect "git commit" "git moved HEAD or refs"
  call "echo y >> f && git checkout -- f";              expect "command discards its own edit (by design)" ""
  user_turn "echo z >> f"
  call "./reset-f.sh";                                  expect "git checkout -- inside a script" "git rewrote these files: f"
  op=$(printf '%s' "$OUT" | sed -n 's/.*jj op restore \([0-9a-f]*\).*/\1/p')
  (cd "$repo" && jj restore --from "at_operation($op, @)" f >/dev/null 2>&1)
  if tail -n 1 "$repo/f" | grep -qx z; then ok "reported jj restore --from brings the file back"; else bad "reported jj restore --from brings the file back" "f ends with [$(tail -n 1 "$repo/f")]"; fi
  call "echo w >> g && jj commit -m c2";                expect "jj commit" ""
  call "echo v >> g; git status; git diff; git describe --always --dirty"
  expect "edit + read-only git right after jj commit (stat refresh)" ""
  user_turn "touch junk"
  call "git clean -fdq";                                expect "git clean -fd keeps files jj tracks" ""
  [ -f "$repo/junk" ] && ok "git clean -fd left the snapshotted file" || bad "git clean -fd left the snapshotted file" "junk was deleted"
  user_turn "echo u >> f"
  call "jj commit -m c3 && echo t >> f && ./reset-f.sh"; expect "jj commit + script git (nothing from before is lost)" ""
  user_turn "echo p >> f"
  call "jj describe -m d && git checkout -- f";         expect "jj op + git checkout in one command" "git rewrote these files: f"
  user_turn "echo r >> g"
  call "git stash -q";                                  expect "git stash" "git rewrote these files: g"
  user_turn "echo s >> h"
  call "jj restore h && git status";                    expect "jj restore + git status (known false positive)" "git rewrote these files: h"
  call "echo q >> g" apply_patch;                       expect "Codex apply_patch (no PreToolUse)" ""
  user_turn "echo k >> f"
  call "./reset-f.sh; false" Bash PostToolUseFailure;   expect "failed command (PostToolUseFailure)" "git rewrote these files: f"
  case $RAW in *'"hookEventName":"PostToolUseFailure"'*) ok "failure report uses the PostToolUseFailure event name" ;; *) bad "failure report uses the PostToolUseFailure event name" "got [$RAW]" ;; esac
  echo m >> "$repo/f"   # someone else edits in the middle of a turn: no UserPromptSubmit
  call "./reset-f.sh";                                  expect "edit by someone else mid-turn (known gap: not protected)" ""

  r=$(ls "$CLAUDE_PLUGIN_DATA/baselines" 2>/dev/null | wc -l | tr -d ' ')
  [ "$r" = 0 ] && ok "no baselines left behind" || bad "no baselines left behind" "$r left"

  # Outside a jj repo: no output, nothing written.
  local data2=$tmp/$label/data-plain
  r=$( (hook_input PreToolUse "$tmp/$label/plain" x Bash "git commit" | CLAUDE_PLUGIN_DATA=$data2 PATH=$hook_path $HB "$P/pre-tool.sh"
        hook_input PostToolUse "$tmp/$label/plain" x Bash "git commit" | CLAUDE_PLUGIN_DATA=$data2 PATH=$hook_path $HB "$P/post-tool.sh") 2>&1)
  if [ -z "$r" ] && [ ! -e "$data2" ]; then ok "outside jj repos: silent, writes nothing"; else bad "outside jj repos: silent, writes nothing" "output [$r]"; fi

  # SessionStart puts the shim on PATH (Claude Code).
  : > "$tmp/$label/env"
  hook_input SessionStart "$repo" x x x | CLAUDE_ENV_FILE=$tmp/$label/env PATH=$hook_path $HB "$P/session-start.sh" >/dev/null
  if grep -q "export PATH=.*$P/shim" "$tmp/$label/env"; then ok "SessionStart adds the shim to PATH"; else bad "SessionStart adds the shim to PATH" "$(cat "$tmp/$label/env")"; fi
}

run_suite full-path "$PATH"
run_suite minimal-path "$(make_nojq_path)"

echo "== shim"
# Two shim copies on PATH (old and new plugin version after an update) must not exec each other.
mkdir -p "$tmp/shim-old" "$tmp/shim-new"
cp "$P/shim/git" "$tmp/shim-old/git"; cp "$P/shim/git" "$tmp/shim-new/git"
r=$(cd "$tmp" && PATH="$tmp/shim-new:$tmp/shim-old:$PATH" perl -e 'alarm 5; exec @ARGV' git --version 2>&1)
case $r in "git version"*) ok "two shims on PATH still reach real git" ;; *) bad "two shims on PATH still reach real git" "got [$r]" ;; esac
r=$(cd "$tmp/full-path/my repo" && PATH="$tmp/shim-new:$PATH" JJ_SHIM_OFF= git commit -qm x 2>&1)
case $r in *"Blocked: this is a jj"*) ok "shim blocks git commit in a jj repo" ;; *) bad "shim blocks git commit in a jj repo" "got [$r]" ;; esac

echo "== no .jj (plain git repo, plain directory)"
# Where there is no .jj the plugin must be inert: every hook silent, nothing written, no jj repo
# created, and git through the shim behaves exactly like git.
g=$tmp/plain-git d=$tmp/plain-dir data3=$tmp/data-nojj
mkdir -p "$g" "$d"
(cd "$g" && git init -q && git config user.email t@example.com && git config user.name t &&
  echo a > a && git add a && git commit -qm first) || bad "plain git repo setup" "git init failed"
for dir in "$g" "$d"; do
  r=$(
    : > "$tmp/env-nojj"
    hook_input SessionStart "$dir" s1 x x | CLAUDE_ENV_FILE=$tmp/env-nojj CLAUDE_PLUGIN_DATA=$data3 $HB "$P/session-start.sh"
    hook_input UserPromptSubmit "$dir" s1 x x | CLAUDE_PLUGIN_DATA=$data3 $HB "$P/user-prompt.sh"
    hook_input PreToolUse "$dir" s2 Bash "git commit -am x" | CLAUDE_PLUGIN_DATA=$data3 $HB "$P/pre-tool.sh"
    hook_input PostToolUse "$dir" s2 Bash "git commit -am x" | CLAUDE_PLUGIN_DATA=$data3 $HB "$P/post-tool.sh"
    hook_input PostToolUseFailure "$dir" s3 Bash "false" | CLAUDE_PLUGIN_DATA=$data3 $HB "$P/post-tool.sh"
    printf '{"session_id":"s1","cwd":"%s","hook_event_name":"PostToolUse","tool_name":"Write","tool_use_id":"s4","tool_input":{"file_path":"%s/a"}}' "$dir" "$dir" |
      CLAUDE_PLUGIN_DATA=$data3 $HB "$P/post-tool.sh"
    echo "rc=$?"
  2>&1)
  name=${dir##*/}
  [ "$r" = "rc=0" ] && ok "$name: every hook silent, exit 0" || bad "$name: every hook silent, exit 0" "got [$r]"
  [ ! -e "$dir/.jj" ] && ok "$name: no .jj created" || bad "$name: no .jj created" ".jj exists"
done
r=$(find "$data3" -type f 2>/dev/null | wc -l | tr -d ' ')
[ "$r" = 0 ] && ok "no state files written" || bad "no state files written" "$(find "$data3" -type f)"
r=$(cd "$g" && PATH="$tmp/shim-new:$PATH" JJ_SHIM_OFF= perl -e 'alarm 10; exec @ARGV' /bin/sh -c '
  echo b >> a && git add a && git commit -qm second &&
  git checkout -q -b feature && echo c >> a && git stash -q && git stash pop -q &&
  git commit -qam third && git checkout -q - && git merge -q --ff-only feature &&
  git reset -q --hard HEAD~1 && git log --format=%s' 2>&1)
[ "$r" = "$(printf 'second\nfirst')" ] && ok "git through the shim works normally (commit, branch, stash, merge, reset)" ||
  bad "git through the shim works normally (commit, branch, stash, merge, reset)" "got [$r]"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
