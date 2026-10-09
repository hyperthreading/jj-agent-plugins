#!/usr/bin/env bash
# Where the time of one hook call goes: each stage of pre-tool.sh / post-tool.sh timed on its own,
# median ms over N runs, in a small and a large generated repo.
#
# usage: tests/hooks-profile.sh [plugin-scripts-dir] [runs]
#   PROFILE_SIZES="10 30000"   number of files in each generated repo
# needs: bash, jj, git, perl
set -u

here=$(cd "$(dirname "$0")" && pwd -P)
P=$(cd "${1:-$here/../plugins/jj-agent/scripts}" && pwd -P) || exit 2
runs=${2:-20}
export JJ_SHIM_OFF=1
# Drop installed jj-agent shims from PATH: measure plain git, not the session's plugin copy.
_p=; IFS=: read -r -a _dirs <<< "$PATH"
for _d in "${_dirs[@]}"; do
  if [ -x "$_d/git" ]; then { IFS= read -r _l1; IFS= read -r _l2; } < "$_d/git" 2>/dev/null
    case $_l2 in "# git shim for Claude Code sessions"*) continue ;; esac; fi
  _p=${_p:+$_p:}$_d
done
export PATH=$_p
HB=bash; [ -x /bin/bash ] && HB=/bin/bash

tmp=$(mktemp -d "${TMPDIR:-/tmp}/jj-agent-profile.XXXXXX") || exit 2
trap '[ -n "$tmp" ] && rm -rf -- "$tmp"' EXIT

# median ms of running shell snippet $1 (via sh -c, outside the timed window: subtracted below)
t() {
  perl -MTime::HiRes=time -e '
    my ($cmd, $n) = @ARGV; my @a;
    for (1 .. $n) { my $t = time; system("/bin/sh", "-c", $cmd); push @a, (time - $t) * 1000 }
    @a = sort { $a <=> $b } @a; printf "%.1f", $a[int($n / 2)]' "$1" "$runs"
}

make_repo() { # dir files
  mkdir -p "$1" && cd "$1" || exit 1
  perl -e 'for my $i (0 .. $ARGV[0] - 1) { my $d = "d" . int($i / 200); mkdir $d;
             open my $f, ">", ($i ? "$d/f$i" : "f0") or die; print $f "line $i\n" x 20 }' "$2"
  jj git init >/dev/null 2>&1 && jj commit -m base >/dev/null 2>&1
  git status >/dev/null 2>&1   # fill index stats, as after any read-only git
  cd - >/dev/null || exit 1
}

row() { printf '%-44s %-5s' "$1" "$2"; shift 2; for v in "$@"; do printf ' %9s' "$v"; done; printf '\n'; }

sizes=${PROFILE_SIZES:-10 30000}
for n in $sizes; do make_repo "$tmp/r$n" "$n"; done

base=$(t ':')
printf 'jj %s, %s, %s runs, median ms (sh -c spawn of %s ms subtracted)\n\n' \
  "$(jj --version | awk '{print $2}')" "$HB" "$runs" "$base"
hdr=(); for n in $sizes; do hdr+=("$n files"); done
row stage hook "${hdr[@]}"

sub() { awk -v a="$1" -v b="$2" 'BEGIN { d = a - b; if (d < 0) d = 0; printf "%.1f", d }'; }
# VALS <- per-repo median ms of snippet $1 (@R@ = repo dir, @OP@ = its head operation), minus the
# sh -c spawn and, if given, minus the per-repo values in array named by $2.
measure_vals() {
  local snip=$1 n r v i=0 prev
  VALS=()
  for n in $sizes; do
    r=$tmp/r$n
    v=$(t "cd '$r' && $(printf '%s' "$snip" | sed -e "s#@R@#$r#g" -e "s#@OP@#$(cat "$r.op")#g")")
    v=$(sub "$v" "$base")
    if [ -n "${2:-}" ]; then eval "prev=\${$2[$i]}"; v=$(sub "$v" "$prev"); fi
    VALS+=("$v"); i=$((i + 1))
  done
}
measure() { measure_vals "$3" "${4:-}"; row "$1" "$2" "${VALS[@]}"; }

for n in $sizes; do
  r=$tmp/r$n
  printf '{"session_id":"p","cwd":"%s","tool_name":"Bash","tool_use_id":"p1","tool_input":{"command":"x","file_path":"%s/f0"}}' "$r" "$r" > "$r.json"
  cp "$r/.git/index" "$r.index"
  jj -R "$r" op log --ignore-working-copy --no-graph -n 1 -T id > "$r.op"
done

measure_vals "$HB -c :"; INTERP=("${VALS[@]}")
row "interpreter start ($HB)" both "${INTERP[@]}"
measure "lib.sh + read input + parse + find root"    both  "$HB -c '. \"$P/lib.sh\"; read_input; json_get cwd c; json_get session_id s; json_get tool_use_id i; json_get file_path f; find_jj_root \"\$c\"' < '@R@.json'" INTERP
measure "jj op log -n1 --ignore-working-copy"         pre   "jj -R '@R@' op log --ignore-working-copy --no-graph -n 1 -T id >/dev/null"
measure "copy git index (cp -c / reflink)"           pre   "cp -c '@R@/.git/index' '@R@.copy' 2>/dev/null || cp '@R@/.git/index' '@R@.copy'"
measure "cmp index vs copy"                          post  "cmp -s '@R@.index' '@R@/.git/index'"
measure "jj op log -n50 (snapshot + ops since)"      post  "jj -R '@R@' op log --no-graph -n 50 -T 'id ++ \"\\t\" ++ description.first_line() ++ \"\\n\"' >/dev/null"
measure "rm baseline files"                          post  ": > '@R@.x'; rm -f '@R@.x' '@R@.y'"
measure "jj util snapshot (after Edit/Write)"        post  "jj -R '@R@' util snapshot >/dev/null 2>&1"
measure "[if index changed] copy index again"        post  "cp -c '@R@/.git/index' '@R@.copy' 2>/dev/null || cp '@R@/.git/index' '@R@.copy'"
measure "[if index changed] jj diff --name-only"     post  "jj diff --ignore-working-copy --from 'at_operation(@OP@, @)' --to @ --name-only >/dev/null"
measure "[if files changed too] ls-files x2 on them" post  "$HB -c '. \"$P/lib.sh\"; git_filled_paths \"@R@\" \"@R@.index\" \"@R@/.git/index\" f0 >/dev/null'" INTERP
