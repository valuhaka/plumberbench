#!/bin/bash
# Oracle: the scripted reference plumber, playing through the same MCP tools as the agent.
set -euo pipefail
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv run --with mcp python3 /solution/solver.py http://mcp-server:8000/mcp "http://mcp-server:8000/facts?token=bc99607452fcebe20606c8e0512cc8d8"
