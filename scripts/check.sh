#!/usr/bin/env bash
# Offline check: no Docker, no model credits. Installs the package, runs the
# test suite, and writes the difficulty ladder to results/ladder.md.
#
#   ./scripts/check.sh            # 100 seeds per level
#   SEEDS=20 ./scripts/check.sh   # quicker
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install -q -e ".[dev]"
python3 -m pytest -q
mkdir -p results
python3 -m plumberbench.ladder --seeds "${SEEDS:-100}" | tee results/ladder.md
