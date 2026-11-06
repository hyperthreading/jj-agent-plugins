#!/usr/bin/env bash
set -eu

root=$(cd "${BASH_SOURCE[0]%/*}/.." && pwd -P)
mode=${1:-write}
case $mode in write|--check) ;; *) echo 'usage: scripts/sync-shared.sh [--check]' >&2; exit 2 ;; esac
stage=$(mktemp -d "${TMPDIR:-/tmp}/jj-guidance-sync.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
mkdir -p "$stage/skills/jj" "$stage/skills/jj-workflow"

skip=0
while IFS= read -r line || [ -n "$line" ]; do
  case $line in
    '<!-- task-flow:start -->')
      printf '%s\n' "$line"
      cat "$root/shared/task-flow.md"
      skip=1 ;;
    '<!-- task-flow:end -->') skip=0; printf '%s\n' "$line" ;;
    *) [ "$skip" = 1 ] || printf '%s\n' "$line" ;;
  esac
done < "$root/plugins/jj-skill/skills/jj/SKILL.md" > "$stage/skills/jj/SKILL.md"
cp "$root/plugins/jj-skill/skills/jj-workflow/SKILL.md" "$stage/skills/jj-workflow/SKILL.md"
while IFS= read -r line || [ -n "$line" ]; do
  if [ "$line" = '{{task-flow}}' ]; then
    head -n 1 "$root/shared/task-flow.md"
  else
    printf '%s\n' "$line"
  fi
done < "$root/shared/preamble.md" > "$stage/preamble.md"

if [ "$mode" = --check ]; then
  diff -ru "$stage/skills" "$root/plugins/jj-skill/skills"
  diff -ru "$stage/skills" "$root/plugins/jj-agent/skills"
  diff -u "$stage/preamble.md" "$root/plugins/jj-agent/scripts/shared/preamble.md"
else
  cp "$stage/skills/jj/SKILL.md" "$root/plugins/jj-skill/skills/jj/SKILL.md"
  mkdir -p "$root/plugins/jj-agent/skills/jj-workflow" "$root/plugins/jj-agent/scripts/shared"
  cp "$stage/skills/jj/SKILL.md" "$root/plugins/jj-agent/skills/jj/SKILL.md"
  cp "$stage/skills/jj-workflow/SKILL.md" "$root/plugins/jj-agent/skills/jj-workflow/SKILL.md"
  cp "$stage/preamble.md" "$root/plugins/jj-agent/scripts/shared/preamble.md"
fi
