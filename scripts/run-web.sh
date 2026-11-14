#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "$0")/.."

uv run -m plumberbench.play --seed $1 --level $2 --web 
