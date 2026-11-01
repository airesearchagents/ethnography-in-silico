#!/usr/bin/env bash
# Run the unit tests from a fresh clone, from any directory.
#
# The repository root is itself a Python package (it has an __init__.py), so
# pytest must treat the folder above it as its root directory and import test
# files in importlib mode.
#
#   scripts/run_tests.sh                                        # all unit tests
#   scripts/run_tests.sh tests/test_methodological_invariants.py
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m pytest --rootdir=.. --import-mode=importlib "${@:-tests}"
