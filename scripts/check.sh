#!/usr/bin/env bash
set -eu
cd "${BASH_SOURCE[0]%/*}/.."
bash tests/skill-sync-test.sh
python3 tests/state-test.py
python3 tests/guidance-test.py
python3 evals/fixtures/grader/test.py
bash tests/hooks-test.sh
