#!/usr/bin/env bash
set -eu
case=${1:?case required}
root=${2:?new directory required}
[ ! -e "$root" ] || { echo "fixture destination exists: $root" >&2; exit 2; }
mkdir -p "$root"
cd "$root"
run() { jj --no-pager --color=never "$@" >/dev/null 2>&1; }
run git init
printf 'base\n' > user.txt
run commit -m base
if [ "$case" != no-trunk ]; then
  run bookmark create main -r @-
  run config set --repo 'revset-aliases."trunk()"' main
fi
case $case in
  empty|no-trunk) ;;
  dirty)
    run describe -m 'user draft'
    printf 'keep this user edit\n' > user.txt ;;
  mid-stack)
    run describe -m 'user draft'
    mid=$(jj log --no-graph -r @ -T change_id)
    run new -m child-one
    run new "$mid" -m child-two
    run edit "$mid" ;;
  mega|mega-unnamed|conflict)
    run describe -m left
    if [ "$case" != conflict ]; then printf 'left\n' > left.txt; else printf 'left\n' > user.txt; fi
    run bookmark create left -r @
    left=left
    if [ "$case" = mega-unnamed ]; then
      run new -m left-tip
      printf 'tip\n' > tip.txt
      left=$(jj log --no-graph -r @ -T change_id)
    fi
    run new main -m right
    if [ "$case" != conflict ]; then printf 'right\n' > right.txt; else printf 'right\n' > user.txt; fi
    run bookmark create right -r @
    run new "$left" right -m megamerge
    if [ "$case" != conflict ]; then run new -m ''; fi ;;
  *) echo "unknown fixture: $case" >&2; exit 2 ;;
esac
run util snapshot
