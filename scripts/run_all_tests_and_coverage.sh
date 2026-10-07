#!/bin/sh
# Note: we need this run in a file as the 'language: system' type in pre-commit-config
# doesn't seem to support multiple commands (even on using &&)
set -e

uv run coverage run --source omr_data_collector -m pytest -rfpsxEX --verbose --durations=3

# The threshold is checked by coverage itself: OMRChecker's script passes
# --cov-fail-under to pytest, but pytest-cov isn't active under `coverage run`, so
# that flag is silently ignored there.
uv run coverage report --fail-under=70

uv run coverage html --ignore-errors
