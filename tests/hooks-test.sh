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
hook_input() { # event cwd tool_use_id tool_name command [more tool_input JSON, e.g. ,"description":"x"]
  printf '{"session_id":"test","cwd":"%s","hook_event_name":"%s","tool_name":"%s","tool_use_id":"%s","tool_input":{"command":"%s"%s}}' \
    "$(json_esc "$2")" "$1" "$4" "$3" "$(json_esc "$5")" "${6:-}"
}

# A minimal PATH without jq or any git shim: the hooks must not depend on either.
make_nojq_path() {
  local d=$tmp/nojq-bin t p dir
  mkdir -p "$d"
  for t in python3 bash sh jj awk sed grep cut tr cksum dirname cat mkdir printf ls wc chmod head find rm ps basename env cp cmp; do
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
call() { # command [tool_name] [post_event] [more tool_input JSON]
  local cmd=$1 tn=${2:-Bash} ev=${3:-PostToolUse} more=${4:-} out
  n=$((n + 1))
  if [ "$tn" = Bash ]; then
    hook_input PreToolUse "$repo" "tu$n" "$tn" "$cmd" "$more" | PATH=$hook_path $HB "$P/pre-tool.sh"
  fi
  (cd "$repo" && eval "$cmd") >/dev/null 2>&1
  out=$(hook_input "$ev" "$repo" "tu$n" "$tn" "$cmd" "$more" | PATH=$hook_path $HB "$P/post-tool.sh")
  RAW=$out
  OUT=$(printf '%s' "$out" | sed -n 's/.*"additionalContext":"\(.*\)"}}$/\1/p')
}

# The user edits files between turns; UserPromptSubmit runs when they send the next prompt.
user_turn() { # shell snippet run in $repo
  (cd "$repo" && eval "$1") >/dev/null 2>&1
  hook_input UserPromptSubmit "$repo" x x x | PATH=$hook_path $HB "$P/user-prompt.sh" >/dev/null
}

# The step named in the newest operation's arguments, or "none". The hooks put it last:
# args: jj ... --config 'jj-agent.step=<step>'   (jj writes a ' inside it as \')
last_step() {
  local a q="'"
  a=$(jj -R "$repo" op log -n 1 --ignore-working-copy --no-graph -T 'attributes' 2>/dev/null)
  case $a in *"jj-agent.step="*) a=${a#*jj-agent.step=}; a=${a%$q}; printf '%s' "${a//\\$q/$q}" ;; *) printf none ;; esac
}
expect_step() { # name expected-step
  local got; got=$(last_step)
  if [ "$got" = "$2" ]; then ok "$1"; else bad "$1" "expected step [$2], got [$got]"; fi
}

reason() { printf '%s' "$OUT" | sed -n 's/.*jj-agent: during the command `.*` that you just ran in [^,]*, \(.*\)\. The repo state.*/\1/p'; }

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
  case $OUT in *'jj-agent: during the command `./reset-f.sh` that you just ran in '*) ok "the report names the command" ;; *) bad "the report names the command" "got [$OUT]" ;; esac
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

  call "for i in \$(seq 55); do jj describe -m d\$i; done; git commit -q --allow-empty -m many"
  expect "git commit after 55 jj operations in the same command" "git moved HEAD or refs"

  # Each snapshot names its step in the operation's arguments (jj op log "args:").
  call "echo n1 >> g" Bash PostToolUse ',"description":"Append a line to g"'
  expect_step "step: the Bash tool's description" "Bash: Append a line to g"
  call "echo n2 >> g"
  expect_step "step: no description, the command" "Bash: echo n2 >> g"
  call "$(printf "sed -i.bak -e 's/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/' g && echo n3 >> g\\nrm -f g.bak")"
  expect_step "step: a long multi-line command is cut to 100 bytes" \
    "Bash: sed -i.bak -e 's/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb..."
  call "echo n4 >> g" Bash PostToolUse ',"description":"가나다라마바사아자차카타파하가나다라마바사아자차카타파하가나다라마바사"'
  expect_step "step: cut at a character boundary (jj rejects broken UTF-8)" \
    "Bash: 가나다라마바사아자차카타파하가나다라마바사아자차카타파하가나다..."
  file_tool() { # tool_input JSON: a file tool's PostToolUse (no PreToolUse, no command run)
    printf '{"session_id":"test","cwd":"%s","hook_event_name":"PostToolUse","tool_name":"%s","tool_use_id":"e1","tool_input":%s}' "$(json_esc "$repo")" "$1" "$2" |
      PATH=$hook_path $HB "$P/post-tool.sh" >/dev/null
  }
  echo n5 >> "$repo/g"
  file_tool apply_patch '{"command":"*** Begin Patch\n*** Update File: g\n@@\n+n5\n*** Add File: sub/new.txt\n+x\n*** End Patch\n"}'
  expect_step "step: Codex patch, by the files it touches" "apply_patch: g, sub/new.txt"
  echo n6 >> "$repo/h"
  file_tool Edit '{"file_path":"'"$(json_esc "$repo")"'/h","old_string":"a","new_string":"b"}'
  expect_step "step: file tool, by the path in the repo" "Edit h"
  user_turn "echo n7 >> h"
  expect_step "step: UserPromptSubmit snapshot" "changes made between turns"

  # File tools reach PreToolUse too (for the Muse hold); outside Muse they are ignored there.
  r=$(printf '{"session_id":"test","cwd":"%s","hook_event_name":"PreToolUse","tool_name":"Write","tool_use_id":"w1","tool_input":{"file_path":"%s/f","content":"x"}}' "$(json_esc "$repo")" "$(json_esc "$repo")" |
      PATH=$hook_path $HB "$P/pre-tool.sh" 2>&1)
  [ -z "$r" ] && [ ! -e "$CLAUDE_PLUGIN_DATA/baselines/w1" ] && ok "PreToolUse for Write: silent, no baseline" || bad "PreToolUse for Write: silent, no baseline" "got [$r]"

  r=$(ls "$CLAUDE_PLUGIN_DATA/baselines" 2>/dev/null | wc -l | tr -d ' ')
  [ "$r" = 0 ] && ok "no baselines left behind" || bad "no baselines left behind" "$r left"
  [ ! -e "$CLAUDE_PLUGIN_DATA/pending" ] && ok "no Muse hold outside Muse" || bad "no Muse hold outside Muse" "$(ls -R "$CLAUDE_PLUGIN_DATA/pending")"

  # .git is a "gitdir:" file (git worktree, --separate-git-dir): the index is found through it.
  local sep="$tmp/$label/sep repo"
  mkdir -p "$sep"
  (cd "$sep" && git init -q --separate-git-dir="$tmp/$label/sep.git" && jj git init --colocate >/dev/null 2>&1 &&
    echo a > f && printf '#!/bin/sh\ngit checkout -- f\n' > reset-f.sh && chmod +x reset-f.sh && jj commit -m base >/dev/null 2>&1) ||
    bad "$label: gitdir-file setup" "failed"
  local main_repo=$repo
  repo=$sep
  user_turn "echo z >> f"
  call "./reset-f.sh";                                  expect ".git is a gitdir: file" "git rewrote these files: f"
  repo=$main_repo

  # Creating a Git worktree must neither convert it nor suppress any imported ref change.
  local wt_ext="$tmp/$label/wt-ext" wt_more="$tmp/$label/wt-more"
  call "git worktree add -q '$wt_ext' -b wt-branch"
  expect "git worktree add reports the new ref" "git moved HEAD or refs"
  [ ! -e "$wt_ext/.jj" ] && [ "$(git -C "$wt_ext" symbolic-ref --short HEAD)" = wt-branch ] &&
    ok "git worktree stays on its branch without .jj" || bad "git worktree stays on its branch without .jj" "$OUT"
  call "git branch unrelated HEAD && jj util snapshot"
  call "git worktree add -q '$wt_more' -b wt-more && git branch -f unrelated HEAD~1"
  expect "worktree creation does not hide unrelated ref moves" "git moved HEAD or refs"

  # First touch initializes the worktree using the parent's shared jj repo.
  repo=$wt_ext
  user_turn "echo dirty >> f"
  [ -f "$wt_ext/.jj/repo" ] && [ ! -e "$wt_ext/.jj/jj-agent-wt" ] &&
    ok "touched worktree shares jj metadata without a plugin marker" ||
    bad "touched worktree shares jj metadata without a plugin marker" "missing shared-repo pointer"
  call "./reset-f.sh"; expect "adopted worktree reports git rewrites" "git rewrote these files: f"
  repo=$main_repo

  # An explicitly created jj workspace has .jj beside its .git file and remains protected.
  local jj_wt="$tmp/$label/jj-workspace"
  (jj -R "$repo" workspace add --colocate --name explicit "$jj_wt" >/dev/null 2>&1) ||
    bad "$label: explicit workspace setup" "failed"
  repo=$jj_wt
  user_turn "echo keep >> f"
  call "./reset-f.sh"; expect "explicit colocated workspace still reports git file rewrites" "git rewrote these files: f"
  repo=$main_repo

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

echo "== muse code (notice inside a tool result, next state-changing call held once)"
m=$tmp/muse-repo; mkdir -p "$m"
(cd "$m" && jj git init >/dev/null 2>&1 && echo a > f && printf '#!/bin/sh\ngit checkout -- f\n' > r.sh && chmod +x r.sh &&
  jj commit -m base >/dev/null 2>&1 && echo keep >> f && jj util snapshot >/dev/null 2>&1) || bad "muse repo setup" "failed"
muse_post() { # tool_use_id tool_response -> MOUT (stdout), MERR (stderr), MRC
  printf '{"hook_event_name":"PostToolUse","tool_name":"bash","tool_input":{"command":"./r.sh"},"tool_use_id":"%s","tool_response":"%s","session_id":"test","cwd":"%s"}' "$1" "$2" "$m" |
    MUSE_PLUGIN_ID=jj-agent CLAUDE_PLUGIN_DATA=$tmp/data-muse $HB "$P/post-tool.sh" > "$tmp/m.out" 2> "$tmp/m.err"
  MRC=$?; MOUT=$(cat "$tmp/m.out"); MERR=$(cat "$tmp/m.err")
}
hook_input UserPromptSubmit "$m" m1 x x | MUSE_PLUGIN_ID=jj-agent CLAUDE_PLUGIN_DATA=$tmp/data-muse $HB "$P/user-prompt.sh" >/dev/null
printf '{"hook_event_name":"PreToolUse","tool_name":"bash","tool_input":{"command":"true"},"tool_use_id":"mu1","session_id":"test","cwd":"%s"}' "$m" |
  MUSE_PLUGIN_ID=jj-agent CLAUDE_PLUGIN_DATA=$tmp/data-muse $HB "$P/pre-tool.sh"
muse_post mu1 '{\n  \"exit_code\": 0,\n  \"output\": \"hello\"\n}'
[ "$MRC" = 0 ] && [ -z "$MOUT$MERR" ] && ok "nothing to report: silent, exit 0" || bad "nothing to report: silent, exit 0" "rc=$MRC out=[$MOUT] err=[$MERR]"
printf '{"hook_event_name":"PreToolUse","tool_name":"bash","tool_input":{"command":"./r.sh"},"tool_use_id":"mu2","session_id":"test","cwd":"%s"}' "$m" |
  MUSE_PLUGIN_ID=jj-agent CLAUDE_PLUGIN_DATA=$tmp/data-muse $HB "$P/pre-tool.sh"
(cd "$m" && ./r.sh) >/dev/null 2>&1
muse_post mu2 '{\n  \"exit_code\": 0,\n  \"output\": \"hello\"\n}'
want_head=$(printf '{\n  "exit_code": 0,\n  "output": "hello"\n}\n\njj-agent: during the command `./r.sh` that you just ran in ')
[ "$MRC" = 2 ] && [ -z "$MOUT" ] && ok "git change: exit 2, nothing on stdout" || bad "git change: exit 2, nothing on stdout" "rc=$MRC out=[$MOUT]"
case $MERR in "$want_head"*"git rewrote these files: f"*) ok "stderr = original tool result, blank line, report" ;; *) bad "stderr = original tool result, blank line, report" "got [$MERR]" ;; esac
muse_pre() { # tool_use_id tool_name command -> MOUT
  printf '{"hook_event_name":"PreToolUse","tool_name":"%s","tool_input":{"command":"%s"},"tool_use_id":"%s","session_id":"test","cwd":"%s"}' "$2" "$3" "$1" "$m" |
    MUSE_PLUGIN_ID=jj-agent CLAUDE_PLUGIN_DATA=$tmp/data-muse $HB "$P/pre-tool.sh" > "$tmp/m.out" 2>&1
  MOUT=$(cat "$tmp/m.out")
}
muse_fail() { # tool_use_id [no-pre]: run ./r.sh as a failed call -> MOUT, MERR, MRC
  if [ -z "${2:-}" ]; then
    echo keep >> "$m/f"; (cd "$m" && jj util snapshot) >/dev/null 2>&1
    muse_pre "$1" bash ./r.sh
  fi
  (cd "$m" && ./r.sh) >/dev/null 2>&1
  printf '{"hook_event_name":"PostToolUseFailure","tool_name":"bash","tool_input":{"command":"./r.sh"},"tool_use_id":"%s","error":"exit 3","session_id":"test","cwd":"%s"}' "$1" "$m" |
    MUSE_PLUGIN_ID=jj-agent CLAUDE_PLUGIN_DATA=$tmp/data-muse $HB "$P/post-tool.sh" > "$tmp/m.out" 2> "$tmp/m.err"
  MRC=$?; MOUT=$(cat "$tmp/m.out"); MERR=$(cat "$tmp/m.err")
}
held() { case $MOUT in *'"permissionDecision":"deny"'*) return 0 ;; esac; return 1; }
pending=$tmp/data-muse/pending/test

[ "$(head -n 1 "$pending" 2>/dev/null)" = delivered ] && ok "the notice is kept as delivered" || bad "the notice is kept as delivered" "$(cat "$pending" 2>&1)"
muse_pre mu3 edit_file ""
held && case $MOUT in *'the result of `./r.sh` reports that git changed this repo'*) true ;; *) false ;; esac &&
  ok "next state-changing call is held, pointing at that result" || bad "next state-changing call is held, pointing at that result" "got [$MOUT]"
[ ! -e "$pending" ] && ok "held once: the notice is cleared" || bad "held once: the notice is cleared" "still there"
muse_pre mu4 edit_file ""
! held && ok "the call after that runs" || bad "the call after that runs" "got [$MOUT]"

echo keep >> "$m/f"; (cd "$m" && jj util snapshot) >/dev/null 2>&1
muse_pre mu5 bash ./r.sh; (cd "$m" && ./r.sh) >/dev/null 2>&1
muse_post mu5 '{\n  \"exit_code\": 0,\n  \"output\": \"hello\"\n}'
muse_pre mu6 bash "jj op log -n 5"
! held && [ ! -e "$pending" ] && ok "after a delivered notice, a jj command runs and clears it" || bad "after a delivered notice, a jj command runs and clears it" "got [$MOUT]"
rm -f "$tmp/data-muse/baselines/mu6"

muse_fail mu7
[ "$MRC" = 0 ] && [ -z "$MOUT$MERR" ] && ok "failed call: silent, result untouched" || bad "failed call: silent, result untouched" "rc=$MRC out=[$MOUT] err=[$MERR]"
[ "$(head -n 1 "$pending" 2>/dev/null)" = undelivered ] && ok "failed call: the notice is kept as undelivered" || bad "failed call: the notice is kept as undelivered" "$(cat "$pending" 2>&1)"
muse_pre mu8 bash "jj op log -n 5"
held && case $MOUT in *'during the command `./r.sh` that you ran earlier in '*'git rewrote these files: f'*) true ;; *) false ;; esac &&
  ok "undelivered: even a jj command is held, and gets the whole notice" || bad "undelivered: even a jj command is held, and gets the whole notice" "got [$MOUT]"
[ ! -e "$tmp/data-muse/baselines/mu8" ] && ok "a held call records no baseline" || bad "a held call records no baseline" "baseline exists"
muse_pre mu9 bash "jj op log -n 5"
! held && ok "the next call runs" || bad "the next call runs" "got [$MOUT]"
rm -f "$tmp/data-muse/baselines/mu9"

# Two calls of one batch pass PreToolUse before either finishes, then both fail.
echo keep >> "$m/f"; (cd "$m" && jj util snapshot) >/dev/null 2>&1
muse_pre mu10 bash ./r.sh; muse_pre mu11 bash ./r.sh
muse_fail mu10 no-pre; muse_fail mu11 no-pre
muse_pre mu12 bash "echo done >> log.txt"
n_notes=$(printf '%s' "$MOUT" | grep -o 'git rewrote these files' | wc -l | tr -d ' ')
[ "$n_notes" = 2 ] && ok "two failed calls: both notices delivered together" || bad "two failed calls: both notices delivered together" "got $n_notes in [$MOUT]"
if command -v python3 >/dev/null 2>&1; then
  printf '%s' "$MOUT" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert d["permissionDecision"]=="deny" and d["permissionDecisionReason"]' 2>/dev/null &&
    ok "the hold is valid PreToolUse JSON" || bad "the hold is valid PreToolUse JSON" "got [$MOUT]"
fi

echo keep >> "$m/f"; (cd "$m" && jj util snapshot) >/dev/null 2>&1
muse_pre mu13 bash ./r.sh; (cd "$m" && ./r.sh) >/dev/null 2>&1
big=$(printf '%*s' 17000 '' | tr ' ' x)
muse_post mu13 '{\n  \"exit_code\": 0,\n  \"output\": \"'"$big"'\"\n}'
[ "$MRC" = 0 ] && [ -z "$MOUT$MERR" ] && [ "$(head -n 1 "$pending" 2>/dev/null)" = undelivered ] &&
  ok "result over 16 KiB: left as it is, the notice goes to the next call" || bad "result over 16 KiB: left as it is, the notice goes to the next call" "rc=$MRC err=${#MERR} bytes, pending=$(head -n 1 "$pending" 2>&1)"
rm -f "$pending"

echo "== no .jj (plain git repo, plain git worktree, plain directory)"
# Where there is no .jj the plugin must be inert: every hook silent, nothing written, no jj repo
# created, and git through the shim behaves exactly like git.
g=$tmp/plain-git gw=$tmp/plain-wt d=$tmp/plain-dir data3=$tmp/data-nojj
mkdir -p "$g" "$d"
(cd "$g" && git init -q && git config user.email t@example.com && git config user.name t &&
  echo a > a && git add a && git commit -qm first && git worktree add -q "$gw" -b wt-plain) || bad "plain git repo setup" "git init failed"
for dir in "$g" "$gw" "$d"; do
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
