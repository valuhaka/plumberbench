#!/bin/bash
# Oracle: the scripted reference plumber, playing through the same MCP tools as the agent.
set -euo pipefail
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv run --with mcp python3 /solution/solver.py http://mcp-server:8000/mcp "http://mcp-server:8000/facts?token=20caa2941998acac612b0b4c10659017"
