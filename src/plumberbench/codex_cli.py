"""Codex as a provider for the local runner (`--provider codex`).

Runs `codex exec` against the episode's MCP server, so a ChatGPT sign-in (and
its plan usage) works: no API key needed. Codex hands the server's pictures to
the model inside the tool results, and passes the server's instructions on.

The run is locked down to the house: the shell, sub-agents, image generation,
goals and web search are off, the sandbox is read-only, the working folder is
empty, your own Codex config is not loaded (so none of your MCP servers or
profiles join in), and PlumberBench's tools are approved without asking, since
`codex exec` has nobody to ask. Calls go one at a time.

The episode ends when a tool result says the job is over (Codex may then write
a last message), when the model stops, or after --max-turns tool calls.

    npm install -g @openai/codex
    codex login
    uv run -m plumberbench.agent run --provider codex --levels 1 --seeds 0-1
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path

JOB_OVER = "The job is over"
SERVER = "plumberbench"
OFF = ("shell_tool", "multi_agent", "image_generation", "goals")
AFTER_OVER = 3  # tool calls allowed after the job is over before Codex is stopped


def find_codex() -> str | None:
    return os.environ.get("PB_CODEX") or shutil.which("codex")


def command(codex: str, url: str, prompt: str, work: Path, model: str | None = None,
            reasoning_effort: str | None = None, extra: tuple[str, ...] = ()) -> list[str]:
    cmd = [codex, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
           "--sandbox", "read-only", "-C", str(work)]
    for feature in OFF:
        cmd += ["--disable", feature]
    cmd += ["-c", f'mcp_servers.{SERVER}.url="{url}"',
            "-c", f'mcp_servers.{SERVER}.default_tools_approval_mode="approve"',
            "-c", f"mcp_servers.{SERVER}.supports_parallel_tool_calls=false",
            "-c", f"mcp_servers.{SERVER}.tool_timeout_sec=300",
            "-c", 'web_search="disabled"', "-c", 'approval_policy="never"']
    if model:
        cmd += ["-m", model]
    if reasoning_effort:
        cmd += ["-c", f'model_reasoning_effort="{reasoning_effort}"']
    return cmd + list(extra) + [prompt]


def _small(line: str) -> str:
    """The event line for the transcript, with pictures' base64 replaced by their size."""
    return re.sub(r'"data":"([A-Za-z0-9+/=]{200,})"', lambda m: f'"data":"<{len(m.group(1))} base64 chars>"', line)


class CodexCLI:
    """Plays a whole episode through `codex exec`; see the module docstring."""

    def __init__(self, model: str | None = None, reasoning_effort: str | None = None, codex: str | None = None,
                 extra: tuple[str, ...] = (), env: dict | None = None):
        self.model, self.reasoning_effort, self.extra, self.env = model, reasoning_effort, tuple(extra), env
        self.codex = codex or find_codex()
        if not self.codex:
            raise SystemExit("Codex is not installed: npm install -g @openai/codex, then codex login.")

    async def play(self, url: str, task: str, max_turns: int, transcript: Path, system: str) -> dict:
        work = transcript.parent / "codex-work"
        work.mkdir(parents=True, exist_ok=True)
        cmd = command(self.codex, url, system + "\n\n" + task, work, self.model, self.reasoning_effort, self.extra)
        (transcript.parent / "codex-command.json").write_text(json.dumps(cmd[:-1], indent=1))
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        calls, after, over, stop, final, warnings, failures = 0, 0, False, None, "", [], []
        with open(transcript.parent / "codex-stderr.txt", "wb") as err, transcript.open("w") as log:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=err,
                env={**os.environ, **(self.env or {})}, limit=64 * 1024 * 1024)
            try:
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    if not line:
                        continue
                    log.write(_small(line) + "\n")
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind, item = ev.get("type"), ev.get("item") or {}
                    if kind == "item.completed" and item.get("type") == "mcp_tool_call":
                        calls += 1
                        after += over
                        over = over or JOB_OVER in json.dumps(item.get("result") or "")
                        if after > AFTER_OVER or (not over and calls >= max_turns):
                            stop = "job over" if over else "max turns"
                            break
                    elif kind == "item.completed" and item.get("type") == "agent_message":
                        final = item.get("text") or ""
                    elif kind == "item.completed" and item.get("type") == "error":
                        warnings.append(item.get("message") or "")  # e.g. unknown model metadata; Codex goes on
                    elif kind in ("turn.failed", "error"):
                        failures.append(json.dumps(ev.get("error") or ev.get("message") or ev)[:500])
                    elif kind == "turn.completed":
                        u = ev.get("usage") or {}
                        cached = u.get("cached_input_tokens", 0) or 0
                        usage["input"] += (u.get("input_tokens", 0) or 0) - cached
                        usage["cache_read"] += cached
                        usage["output"] += u.get("output_tokens", 0) or 0
            finally:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
        if stop is None:
            if over:
                stop = "job over"
            elif failures or proc.returncode not in (0, None):
                stop = "codex failed: " + ((failures or ["see codex-stderr.txt"])[-1])[:300]
            else:
                stop = "model stopped"
        return {"turns": calls, "tool_calls": calls, "stop": stop, "usage": usage, "final": final}
