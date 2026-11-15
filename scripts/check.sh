#!/usr/bin/env bash
# Offline check: no Docker, no model credits. Runs the test suite and writes
# the difficulty ladder to results/ladder.md. Uses uv when it is installed,
# otherwise pip into the current Python.
#
# The screen-size test (tests/test_page_layout.py) needs a browser: Playwright's
# own Chromium if installed, otherwise Google Chrome or Edge. Without one it is
# skipped, and the summary at the end says which tests were skipped and why.
#
#   ./scripts/check.sh            # 100 seeds per level
#   SEEDS=20 ./scripts/check.sh   # quicker
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1; then
  run() { uv run --extra dev "$@"; }
else
  python3 -m pip install -q -e ".[dev]"
  run() { "$@"; }
fi

run python3 -m pytest -q -rs
mkdir -p results
run python3 -m plumberbench.ladder --seeds "${SEEDS:-100}" --json results/ladder.json | tee results/ladder.md
