#!/bin/sh
# One-time install for fresh worktrees: sync locked deps so
# `.venv/bin/python -m pytest` and `just check` work offline-first.
set -eu
cd "$(dirname "$0")/.."
uv sync --locked
