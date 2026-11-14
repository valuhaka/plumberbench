"""Baseline agents for Harbor, run alongside the built-in `nop` (do nothing).

    harbor run -p harbor/tasks/l3-s007-facts --agent pb_agents.baselines:StopEarlyAgent
    harbor run -p harbor/tasks/l3-s007-facts --agent pb_agents.baselines:CloseMainAgent

Run with the repository root on PYTHONPATH so `pb_agents` is importable:
    PYTHONPATH=. harbor run ... Neither agent uses a model.

StopEarlyAgent   reads the briefing, then calls `finish` naming the fault the
                 tenant's complaint suggests, without touching anything.
CloseMainAgent   walks to the utility room, shuts the main valve (every leak
                 stops) and finishes. The house test fails: no tap has water.
"""
from __future__ import annotations

import shlex

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

CLIENT = r'''
import asyncio, json, re, sys
from mcp.client.session import ClientSession
try:
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

PLAN = sys.argv[1]

async def main():
    async with streamablehttp_client("http://mcp-server:8000/mcp") as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            async def call(tool, **args):
                r = await s.call_tool(tool, args)
                text = "\n".join(c.text for c in r.content if getattr(c, "text", None))
                print(f"{tool} {args} -> {text.splitlines()[1] if chr(10) in text else text}")
                return text
            brief = await call("briefing")
            if PLAN == "stop_early":
                guess = "trap_clog"
                if "leak" in brief or "wet" in brief or "water under" in brief:
                    guess = "drain_leak" if "drain" in brief else "supply_leak"
                elif "weak" in brief or "barely" in brief:
                    guess = "aerator_clog"
                elif "No " in brief:
                    guess = "valve_not_open"
                await call("finish", diagnosis=[guess])
            elif PLAN == "close_main":
                await call("go", room="utility")
                wall = await call("look", view="wall")
                facts = next((l[6:] for l in wall.splitlines() if l.startswith("FACTS ")), None)
                if facts:
                    main = next(f["tag"] for f in json.loads(facts) if f.get("role") == "main")
                    await call("set_valve", tag=main, position="closed")
                else:  # images only: it cannot tell which valve is the main, so it shuts them all
                    tags = re.search(r"Tags in view: (.*)", wall).group(1).split()
                    for t in tags:
                        if t.startswith("V"):
                            await call("set_valve", tag=t, position="closed")
                await call("finish", diagnosis=["supply_leak"])

asyncio.run(main())
'''


class _ScriptAgent(BaseAgent):
    PLAN = ""

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        await environment.exec(command="curl -LsSf https://astral.sh/uv/install.sh | sh", timeout_sec=300)

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        script = "/tmp/baseline_client.py"
        await environment.exec(command=f"cat > {script} << 'PYEOF'\n{CLIENT}\nPYEOF")
        result = await environment.exec(
            command=f"$HOME/.local/bin/uv run --with mcp python3 {script} {shlex.quote(self.PLAN)}",
            timeout_sec=600,
        )
        (self.logs_dir / f"{self.PLAN}.log").write_text(
            f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}")


class StopEarlyAgent(_ScriptAgent):
    PLAN = "stop_early"

    @staticmethod
    def name() -> str:
        return "plumberbench-stop-early"


class CloseMainAgent(_ScriptAgent):
    PLAN = "close_main"

    @staticmethod
    def name() -> str:
        return "plumberbench-close-main"
