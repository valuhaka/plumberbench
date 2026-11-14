#!/bin/bash
# Oracle for the smoke test: calls show_number five times and reads the last
# picture by matching each digit against the same font. It checks the
# artifact and verifier plumbing without spending model credits.
set -euo pipefail
apt-get update -qq && apt-get install -y -qq fonts-dejavu-core > /dev/null
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv run --with mcp --with pillow --with numpy python3 /solution/read_number.py \
    http://mcp-server:8000/mcp /app/answer.txt
