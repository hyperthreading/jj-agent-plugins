#!/usr/bin/env bash
# The jj skill ships in two plugins: jj-agent (with hooks) and jj-skill (skill only). The copies
# must stay identical; edit one and copy it over the other.
#
# usage: tests/skill-sync-test.sh
set -u

here=$(cd "$(dirname "$0")" && pwd -P)
a=$here/../plugins/jj-agent/skills
b=$here/../plugins/jj-skill/skills
if diff -r "$a" "$b"; then
  printf '  ok    plugins/jj-agent/skills and plugins/jj-skill/skills match\n'
else
  printf '  FAIL  plugins/jj-agent/skills and plugins/jj-skill/skills differ (diff above)\n'
  exit 1
fi
