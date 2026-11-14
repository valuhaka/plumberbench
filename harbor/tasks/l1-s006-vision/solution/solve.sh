#!/bin/bash
# Oracle: the scripted reference plumber, playing through the same MCP tools as the agent.
set -euo pipefail
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv run --with mcp python3 /solution/solver.py http://mcp-server:8000/mcp "http://mcp-server:8000/facts?token=651a12d7a543056fd42d62adfb379ef0"
