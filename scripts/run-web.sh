#!/usr/bin/env bash
# Play a house in the browser.
#
#   ./scripts/run-web.sh                 # house 0, level 1
#   ./scripts/run-web.sh 3 2             # house 3, level 2
#   ./scripts/run-web.sh 3 2 --facts     # also show the FACTS list (not for playtests)
#
# Extra arguments go to `plumberbench.play` (for example --port 8900 or --no-browser).
# Uses uv when it is installed, otherwise the current Python.
set -euo pipefail
cd "$(dirname "$0")/.."

seed="${1:-0}"
level="${2:-1}"
shift $(( $# > 2 ? 2 : $# ))

if command -v uv >/dev/null 2>&1; then
  exec uv run python3 -m plumberbench.play --web --seed "$seed" --level "$level" "$@"
else
  python3 -m pip install -q -e .
  exec python3 -m plumberbench.play --web --seed "$seed" --level "$level" "$@"
fi
