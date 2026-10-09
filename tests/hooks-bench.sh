#!/usr/bin/env bash
# Latency of the jj-agent hooks per tool call, by repo size. Prints the median wall time in ms.
#
# usage: tests/hooks-bench.sh [plugin-scripts-dir] [runs]
#   BENCH_SIZES="10 5000 30000"   number of files in each generated repo
# needs: bash, jj, git, perl
#
# Columns:
#   pre            PreToolUse before a Bash command (snapshot + baseline + index copy)
#   post           PostToolUse after a Bash command that changed nothing
#   post+git       PostToolUse after a command where git rewrote one file (per-path check runs)
#   post(edit)     PostToolUse after an Edit/Write: snapshot only, the per-step cost before 0.3.0
set -u

here=$(cd "$(dirname "$0")" && pwd -P)
P=$(cd "${1:-$here/../plugins/jj-agent/scripts}" && pwd -P) || exit 2
runs=${2:-15}
export JJ_SHIM_OFF=1
# Drop installed jj-agent shims from PATH: measure plain git, not the session's plugin copy.
_p=; IFS=: read -r -a _dirs <<< "$PATH"
for _d in "${_dirs[@]}"; do
  if [ -x "$_d/git" ]; then { IFS= read -r _l1; IFS= read -r _l2; } < "$_d/git" 2>/dev/null
    case $_l2 in "# git shim for Claude Code sessions"*) continue ;; esac; fi
  _p=${_p:+$_p:}$_d
done
export PATH=$_p

tmp=$(mktemp -d "${TMPDIR:-/tmp}/jj-agent-bench.XXXXXX") || exit 2
trap '[ -n "$tmp" ] && rm -rf -- "$tmp"' EXIT
export CLAUDE_PLUGIN_DATA=$tmp/data
HB=bash; [ -x /bin/bash ] && HB=/bin/bash   # interpreter, as in hooks.json

input() { # event cwd tool_name
  printf '{"session_id":"bench","cwd":"%s","hook_event_name":"%s","tool_name":"%s","tool_use_id":"b1","tool_input":{"command":"x","file_path":"%s/f0"}}' "$2" "$1" "$3" "$2"
}
# ms for one hook run; perl's own startup is outside the measured window.
timed() { # script event cwd tool_name
  input "$2" "$3" "$4" > "$tmp/in.json"
  perl -MTime::HiRes=time -e 'my $t = time; system($ARGV[1], $ARGV[0]); printf "%.1f\n", (time - $t) * 1000' \
    "$1" "$HB" < "$tmp/in.json" 2>/dev/null
}
median() { sort -n | awk '{ a[NR] = $1 } END { print (NR % 2) ? a[(NR + 1) / 2] : (a[NR / 2] + a[NR / 2 + 1]) / 2 }'; }

bench_repo() { # label dir is_jj
  local label=$1 d=$2 i pre post postg edit
  : > "$tmp/pre" ; : > "$tmp/post"; : > "$tmp/postg"; : > "$tmp/edit"
  for i in $(seq "$runs"); do
    timed "$P/pre-tool.sh" PreToolUse "$d" Bash >> "$tmp/pre"
    timed "$P/post-tool.sh" PostToolUse "$d" Bash >> "$tmp/post"
    if [ "$3" = 1 ]; then
      echo "edit $i" >> "$d/f0"
      (cd "$d" && jj util snapshot >/dev/null 2>&1)
      input PreToolUse "$d" Bash | $HB "$P/pre-tool.sh"
      (cd "$d" && git checkout -- f0 2>/dev/null)
      timed "$P/post-tool.sh" PostToolUse "$d" Bash >> "$tmp/postg"
      echo "edit $i" >> "$d/f0"
      timed "$P/post-tool.sh" PostToolUse "$d" Edit >> "$tmp/edit"
    fi
  done
  pre=$(median < "$tmp/pre"); post=$(median < "$tmp/post")
  postg=$( [ -s "$tmp/postg" ] && median < "$tmp/postg" || echo -)
  edit=$( [ -s "$tmp/edit" ] && median < "$tmp/edit" || echo -)
  printf '%-22s %8s %8s %9s %11s\n' "$label" "$pre" "$post" "$postg" "$edit"
}

make_repo() { # dir files
  mkdir -p "$1" && cd "$1" || exit 1
  perl -e 'for my $i (0 .. $ARGV[0] - 1) { my $d = "d" . int($i / 200); mkdir $d;
             open my $f, ">", ($i ? "$d/f$i" : "f0") or die; print $f "line $i\n" x 20 }' "$2"
  jj git init >/dev/null 2>&1 && jj commit -m base >/dev/null 2>&1
  cd - >/dev/null || exit 1
}

printf 'jj %s, git %s, %s runs, median ms\n\n' "$(jj --version | awk '{print $2}')" "$(git --version | awk '{print $3}')" "$runs"
printf '%-22s %8s %8s %9s %11s\n' repo pre post post+git 'post(edit)'
mkdir -p "$tmp/plain"
bench_repo "not a jj repo" "$tmp/plain" 0
for n in ${BENCH_SIZES:-10 5000 30000}; do
  make_repo "$tmp/r$n" "$n"
  idx=$(wc -c < "$tmp/r$n/.git/index" | tr -d ' ')
  bench_repo "$n files ($((idx / 1024)) KiB idx)" "$tmp/r$n" 1
done
