#!/usr/bin/env bash
# Scenario tests for the jj-agent hooks. Each scenario runs a command between the PreToolUse and
# PostToolUse hooks, the way Claude Code and Codex call them for a Bash tool call, and checks the
# git-change report. Every scenario runs twice: with jq on PATH and without it.
#
# usage: tests/hooks-test.sh [plugin-scripts-dir]   (default: plugins/jj-agent/scripts)
# needs: bash, jj, git
set -u

here=$(cd "$(dirname "$0")" && pwd -P)
P=$(cd "${1:-$here/../plugins/jj-agent/scripts}" && pwd -P) || exit 2
export JJ_SHIM_OFF=1   # scenarios run git directly; this only matters when a git shim is on PATH

tmp=$(mktemp -d "${TMPDIR:-/tmp}/jj-agent-test.XXXXXX") || exit 2
trap '[ -n "$tmp" ] && rm -rf -- "$tmp"' EXIT

pass=0 fail=0
ok()  { pass=$((pass + 1)); printf '  ok    %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL  %s\n        %s\n' "$1" "$2"; }

json_esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
hook_input() { # event cwd tool_use_id tool_name command
  printf '{"session_id":"test","cwd":"%s","hook_event_name":"%s","tool_name":"%s","tool_use_id":"%s","tool_input":{"command":"%s"}}' \
    "$(json_esc "$2")" "$1" "$4" "$3" "$(json_esc "$5")"
}

# A PATH without jq (and without any git shim), to exercise the hooks' grep/sed fallback.
make_nojq_path() {
  local d=$tmp/nojq-bin t p dir
  mkdir -p "$d"
  for t in bash sh jj awk sed grep cut tr cksum dirname cat mkdir printf ls wc chmod head find rm ps basename env cp; do
    p=$(type -P "$t") && ln -sf "$p" "$d/$t"
  done
  # real git: the first git on PATH that is not a shim
  local IFS=:
  for dir in $PATH; do
    if [ -x "$dir/git" ] && ! grep -q 'git shim' "$dir/git" 2>/dev/null; then ln -sf "$dir/git" "$d/git"; break; fi
  done
  printf '%s' "$d"
}

# Run one tool call against $repo: pre hook (Bash only), the command, post hook. Sets OUT to the
# additionalContext text (empty if none).
call() { # command [tool_name]
  local cmd=$1 tn=${2:-Bash} out
  n=$((n + 1))
  if [ "$tn" = Bash ]; then
    hook_input PreToolUse "$repo" "tu$n" "$tn" "$cmd" | PATH=$hook_path bash "$P/pre-tool.sh"
  fi
  (cd "$repo" && eval "$cmd") >/dev/null 2>&1
  out=$(hook_input PostToolUse "$repo" "tu$n" "$tn" "$cmd" | PATH=$hook_path bash "$P/post-tool.sh")
  OUT=$(printf '%s' "$out" | sed -n 's/.*"additionalContext":"\(.*\)"}}$/\1/p')
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
  repo=$tmp/$label/repo
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
  echo z >> "$repo/f"
  call "./reset-f.sh";                                  expect "git checkout -- inside a script" "git rewrote these files: f"
  op=$(printf '%s' "$OUT" | sed -n 's/.*jj op restore \([0-9a-f]*\).*/\1/p')
  (cd "$repo" && jj restore --from "at_operation($op, @)" f >/dev/null 2>&1)
  if tail -n 1 "$repo/f" | grep -qx z; then ok "reported jj restore --from brings the file back"; else bad "reported jj restore --from brings the file back" "f ends with [$(tail -n 1 "$repo/f")]"; fi
  call "echo w >> g && jj commit -m c2";                expect "jj commit" ""
  call "echo v >> g; git status; git diff; git describe --always --dirty"
  expect "edit + read-only git right after jj commit (stat refresh)" ""
  touch "$repo/junk"
  call "git clean -fdq";                                expect "git clean -fd keeps files jj tracks" ""
  [ -f "$repo/junk" ] && ok "git clean -fd left the snapshotted file" || bad "git clean -fd left the snapshotted file" "junk was deleted"
  echo u >> "$repo/f"
  call "jj commit -m c3 && echo t >> f && ./reset-f.sh"; expect "jj commit + script git (nothing from before is lost)" ""
  echo p >> "$repo/f"
  call "jj describe -m d && git checkout -- f";         expect "jj op + git checkout in one command" "git rewrote these files: f"
  echo r >> "$repo/g"
  call "git stash -q";                                  expect "git stash" "git rewrote these files: g"
  echo s >> "$repo/h"
  call "jj restore h && git status";                    expect "jj restore + git status (known false positive)" "git rewrote these files: h"
  call "echo q >> g" apply_patch;                       expect "Codex apply_patch (no PreToolUse)" ""

  r=$(ls "$CLAUDE_PLUGIN_DATA/baselines" 2>/dev/null | wc -l | tr -d ' ')
  [ "$r" = 0 ] && ok "no baselines left behind" || bad "no baselines left behind" "$r left"

  # Outside a jj repo: no output, nothing written.
  local data2=$tmp/$label/data-plain
  r=$( (hook_input PreToolUse "$tmp/$label/plain" x Bash "git commit" | CLAUDE_PLUGIN_DATA=$data2 PATH=$hook_path bash "$P/pre-tool.sh"
        hook_input PostToolUse "$tmp/$label/plain" x Bash "git commit" | CLAUDE_PLUGIN_DATA=$data2 PATH=$hook_path bash "$P/post-tool.sh") 2>&1)
  if [ -z "$r" ] && [ ! -e "$data2" ]; then ok "outside jj repos: silent, writes nothing"; else bad "outside jj repos: silent, writes nothing" "output [$r]"; fi

  # SessionStart puts the shim on PATH (Claude Code).
  : > "$tmp/$label/env"
  hook_input SessionStart "$repo" x x x | CLAUDE_ENV_FILE=$tmp/$label/env PATH=$hook_path bash "$P/session-start.sh" >/dev/null
  if grep -q "export PATH=.*$P/shim" "$tmp/$label/env"; then ok "SessionStart adds the shim to PATH"; else bad "SessionStart adds the shim to PATH" "$(cat "$tmp/$label/env")"; fi
}

if command -v jq >/dev/null 2>&1; then run_suite with-jq "$PATH"; else echo "== with-jq: skipped (jq not installed)"; fi
run_suite without-jq "$(make_nojq_path)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
