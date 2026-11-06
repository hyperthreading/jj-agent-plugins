#!/usr/bin/env bash
set -eu
exec python3 "${BASH_SOURCE[0]%/*}/runner.py" "$@"
