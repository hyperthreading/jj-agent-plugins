#!/usr/bin/env bash
# Skills and the preamble are generated from shared content and the jj-skill source.
#
# usage: tests/skill-sync-test.sh
set -u

here=$(cd "$(dirname "$0")" && pwd -P)
if bash "$here/../scripts/sync-shared.sh" --check; then
  printf '  ok    shared task flow, preamble, and both skill distributions match\n'
else
  printf '  FAIL  generated guidance differs; run bash scripts/sync-shared.sh\n'
  exit 1
fi
