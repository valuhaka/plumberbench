"""Run a model on PlumberBench locally: no Docker, no Harbor, the real MCP server.

Each episode starts its own `plumberbench.server` and connects to it over MCP,
exactly as OpenCode does inside Harbor: same tools, descriptions, server
instructions, pictures and text. The model gets the task instruction as the
user message. Results land in runs/ with the server's log, a transcript, a
replay page and a summary.

The key comes from ANTHROPIC_API_KEY or OPENAI_API_KEY, or the variable named by --key-env.

    export ANTHROPIC_API_KEY=...
    python -m plumberbench.agent run --provider anthropic --model MODEL --levels 1 2 --seeds 0-1
    python -m plumberbench.agent run --provider openai --model MODEL
    python -m plumberbench.agent run --provider openai --model MODEL --reasoning-effort none
    python -m plumberbench.agent run --provider openai --model MODEL \\
        --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --key-env GEMINI_API_KEY
    python -m plumberbench.agent smoke --provider anthropic --model MODEL --repeat 3
    uv run --extra agents -m plumberbench.agent run --provider openai-agents --model MODEL
    python -m plumberbench.agent run --provider codex          # your Codex sign-in; no API key

Providers:
    anthropic  Messages API. Pictures go inside tool results. Prompt caching on:
               the system prompt, the tools and a rolling breakpoint on the latest
               message, so each turn re-reads earlier turns from cache.
    openai     Any OpenAI-compatible Chat Completions endpoint (OpenAI, Gemini's
               compatible endpoint, OpenRouter, vLLM, ...). Tool results are text;
               their pictures follow in one user message, as OpenCode does.
               --reasoning-effort sets `reasoning_effort`; OpenAI's newer models
               allow function calling over Chat Completions only with `none`.
    openai-agents  The OpenAI Agents SDK, over the Responses API: its own agent loop,
               reasoning on while calling tools, pictures inside tool results,
               traces in the OpenAI dashboard. See agents_sdk.py.
    codex      `codex exec` against the episode's server, signed in as you are in
               Codex (a ChatGPT plan works); --model optional. See codex_cli.py.
    scripted   No model: replays a list of tool calls (for tests and dry runs).

`smoke` runs the vision smoke test (harbor/smoke-vision) against a model:
five pictures of numbers, answer the fifth. PASS, STALE or BLIND, as in Harbor.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE_SERVER = ROOT / "harbor" / "smoke-vision" / "environment" / "mcp-server" / "server.py"
SYSTEM = ("You are an autonomous agent. You act only by calling the tools you are given, one action per "
          "call, and you keep going until the task is done. Look carefully at every picture you get.")
SMOKE_TASK = ("The `smoke` MCP server has one tool, `show_number`. Each call returns a picture of a new "
              "six-digit number; the text of the response does not contain it. Call `show_number` exactly "
              "five times, one call at a time. Then reply with only the number shown in the picture from "
              "the fifth call, digits only, and stop.")


# ------------------------------------------------------------------ data

@dataclass
class Call:
    id: str
    name: str
    args: dict


@dataclass
class Result:
    call: Call
    text: str
    images: list[tuple[str, str]] = field(default_factory=list)  # (mime type, base64 data)
    error: bool = False


@dataclass
class Turn:
    text: str
    calls: list[Call]
    usage: dict
    cut_off: bool = False  # the reply hit the output-token limit (thinking counts towards it)


# --------------------------------------------------------------- providers

def post_json(url: str, headers: dict, body: dict, timeout: float = 300.0) -> dict:
    """POST with retries on rate limits and server errors. Replaced in tests."""
    data = json.dumps(body).encode()
    for attempt in range(6):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:2000]
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < 5:
                time.sleep(min(60, 2 ** attempt * 3))
                continue
            raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < 5:
                time.sleep(min(60, 2 ** attempt * 3))
                continue
            raise
    raise RuntimeError("unreachable")


class Anthropic:
    """Claude through the Messages API, with prompt caching."""

    def __init__(self, model: str, key: str, base_url: str | None = None, max_tokens: int = 16000):
        self.model, self.key, self.max_tokens = model, key, max_tokens
        self.url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        self.messages: list[dict] = []

    def start(self, system: str, task: str, tools: list[dict]) -> None:
        self.system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]}
                      for t in tools]
        if self.tools:
            self.tools[-1]["cache_control"] = {"type": "ephemeral"}
        self.messages = [{"role": "user", "content": [{"type": "text", "text": task}]}]

    def request(self) -> dict:
        # One rolling cache breakpoint: on the last block of the latest message only.
        for m in self.messages:
            if isinstance(m["content"], list):
                for block in m["content"]:
                    block.pop("cache_control", None)
        self.messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
        return {"model": self.model, "max_tokens": self.max_tokens, "system": self.system,
                "tools": self.tools, "messages": self.messages}

    def step(self) -> Turn:
        r = post_json(self.url, {"x-api-key": self.key, "anthropic-version": "2023-06-01"}, self.request())
        content = r.get("content", [])
        self.messages.append({"role": "assistant", "content": content})
        calls = [Call(b["id"], b["name"], b.get("input") or {}) for b in content if b.get("type") == "tool_use"]
        text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
        u = r.get("usage", {})
        return Turn(text, calls, {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                                  "cache_read": u.get("cache_read_input_tokens", 0),
                                  "cache_write": u.get("cache_creation_input_tokens", 0)},
                    cut_off=r.get("stop_reason") == "max_tokens")

    def add_results(self, results: list[Result]) -> None:
        blocks = []
        for res in results:
            content = [{"type": "text", "text": res.text}] + [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
                for mime, data in res.images]
            blocks.append({"type": "tool_result", "tool_use_id": res.call.id, "content": content,
                           "is_error": res.error})
        self.messages.append({"role": "user", "content": blocks})


class OpenAICompatible:
    """Any OpenAI-compatible Chat Completions endpoint."""

    def __init__(self, model: str, key: str, base_url: str | None = None, max_tokens: int = 16000,
                 reasoning_effort: str | None = None):
        self.model, self.key, self.max_tokens = model, key, max_tokens
        self.reasoning_effort = reasoning_effort
        self.url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        self.messages: list[dict] = []

    def start(self, system: str, task: str, tools: list[dict]) -> None:
        self.tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                        "parameters": t["schema"]}} for t in tools]
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]

    def request(self) -> dict:
        body = {"model": self.model, "messages": self.messages, "tools": self.tools,
                "max_completion_tokens": self.max_tokens}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def step(self) -> Turn:
        r = post_json(self.url, {"authorization": f"Bearer {self.key}"}, self.request())
        choice = r["choices"][0]
        msg = choice["message"]
        keep = {"role": "assistant", "content": msg.get("content")}
        if msg.get("tool_calls"):
            keep["tool_calls"] = msg["tool_calls"]
        self.messages.append(keep)
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparsed": c["function"].get("arguments")}
            calls.append(Call(c["id"], c["function"]["name"], args))
        u = r.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        return Turn(msg.get("content") or "", calls,
                    {"input": u.get("prompt_tokens", 0) - cached, "output": u.get("completion_tokens", 0),
                     "cache_read": cached, "cache_write": 0},
                    cut_off=choice.get("finish_reason") == "length")

    def add_results(self, results: list[Result]) -> None:
        pictures = []
        for res in results:
            self.messages.append({"role": "tool", "tool_call_id": res.call.id, "content": res.text})
            pictures += [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
                         for mime, data in res.images]
        if pictures:
            self.messages.append({"role": "user", "content": [
                {"type": "text", "text": "Pictures from the tool results above:"}, *pictures]})


class Scripted:
    """No model: makes the given tool calls one per turn, then says `final`.

    `reader`, if given, is called with each result and may return the final
    answer (used to test that pictures arrive, without a model).
    """

    def __init__(self, calls: list[tuple[str, dict]], final: str = "Done.", reader=None):
        self.calls, self.final, self.reader, self.i = list(calls), final, reader, 0
        self.seen: list[Result] = []

    def start(self, system: str, task: str, tools: list[dict]) -> None:
        self.tools = tools

    def step(self) -> Turn:
        if self.i >= len(self.calls):
            return Turn(self.final, [], {})
        name, args = self.calls[self.i]
        self.i += 1
        return Turn("", [Call(f"call-{self.i}", name, args)], {})

    def add_results(self, results: list[Result]) -> None:
        self.seen += results
        if self.reader:
            for res in results:
                answer = self.reader(res)
                if answer is not None:
                    self.final = answer


def make_provider(args) -> object:
    if args.provider == "scripted":
        raise SystemExit("The scripted provider is for tests; give it calls in code.")
    if args.provider == "codex":
        from .codex_cli import CodexCLI
        return CodexCLI(args.model, args.reasoning_effort)
    if not args.model:
        raise SystemExit(f"--model is required for --provider {args.provider}.")
    env = args.key_env or {"anthropic": "ANTHROPIC_API_KEY"}.get(args.provider, "OPENAI_API_KEY")
    key = os.environ.get(env)
    if not key:
        raise SystemExit(f"Set {env} (or pass --key-env NAME).")
    if args.provider == "anthropic":
        if args.reasoning_effort:
            raise SystemExit("--reasoning-effort is for the OpenAI providers.")
        return Anthropic(args.model, key, args.base_url, args.max_tokens)
    if args.provider == "openai-agents":
        try:
            from .agents_sdk import AgentsSDK
            import agents  # noqa: F401
        except ImportError:
            raise SystemExit("The Agents SDK is not installed: run with  uv run --extra agents -m plumberbench.agent ...")
        return AgentsSDK(args.model, key, args.base_url, args.max_tokens, args.reasoning_effort)
    return OpenAICompatible(args.model, key, args.base_url, args.max_tokens, args.reasoning_effort)


# ------------------------------------------------------------ MCP sessions

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_process(cmd: list[str], env: dict, health: str, log_path: Path) -> subprocess.Popen:
    log = open(log_path, "w")
    proc = subprocess.Popen(cmd, env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(240):
        if proc.poll() is not None:
            raise RuntimeError(f"server exited; see {log_path}")
        try:
            urllib.request.urlopen(health, timeout=1)
            return proc
        except OSError:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError(f"server did not start; see {log_path}")


def start_plumberbench(seed: int, level: int, facts: bool, log_dir: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    src = str(Path(__file__).resolve().parents[1])
    env = {"PB_SEED": str(seed), "PB_LEVEL": str(level), "PB_FACTS": "1" if facts else "0", "PB_RENDER": "1",
           "PB_LOG_DIR": str(log_dir / "server"), "PB_PORT": str(port),
           "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = start_process([sys.executable, "-m", "plumberbench.server"], env,
                         f"http://127.0.0.1:{port}/health", log_dir / "server.log")
    return proc, f"http://127.0.0.1:{port}/mcp"


async def play(provider, url: str, task: str, max_turns: int, transcript: Path) -> dict:
    """The agent loop: the model calls tools, the server answers, until the job ends or the model stops."""
    if hasattr(provider, "play"):  # a provider with its own agent loop (the Agents SDK)
        return await provider.play(url, task, max_turns, transcript, SYSTEM)
    from mcp.client.session import ClientSession
    try:
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    turns, calls, stop, final = 0, 0, "max turns", ""
    async with streamablehttp_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            tools = [{"name": t.name, "description": t.description or "",
                      "schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}}
                     for t in listed.tools]
            instructions = getattr(init, "instructions", None) or ""
            provider.start(SYSTEM + ("\n\n" + instructions if instructions else ""), task, tools)
            with transcript.open("w") as log:
                for turns in range(1, max_turns + 1):
                    turn = await asyncio.to_thread(provider.step)
                    for k in usage:
                        usage[k] += turn.usage.get(k, 0)
                    log.write(json.dumps({"turn": turns, "text": turn.text, "usage": turn.usage,
                                          "calls": [[c.name, c.args] for c in turn.calls]}) + "\n")
                    if not turn.calls:
                        stop = "cut off: raise --max-tokens" if turn.cut_off else "model stopped"
                        final = turn.text
                        break
                    results, over = [], False
                    for c in turn.calls:  # one at a time, in order
                        calls += 1
                        r = await session.call_tool(c.name, c.args)
                        text = "\n".join(x.text for x in r.content if getattr(x, "type", "") == "text")
                        images = [(getattr(x, "mime_type", None) or getattr(x, "mimeType", None) or "image/jpeg",
                                   x.data) for x in r.content if getattr(x, "type", "") == "image"]
                        error = bool(getattr(r, "is_error", getattr(r, "isError", False)))
                        results.append(Result(c, text, images, error))
                        log.write(json.dumps({"turn": turns, "tool": c.name, "args": c.args, "result": text,
                                              "pictures": len(images)}) + "\n")
                        over = over or "The job is over" in text
                    provider.add_results(results)
                    if over:
                        stop = "job over"
                        break
    return {"turns": turns, "tool_calls": calls, "stop": stop, "usage": usage, "final": final}


# ------------------------------------------------------------------- runs

def episode(provider, seed: int, level: int, facts: bool, out: Path, max_turns: int) -> dict:
    from .replay import build
    from .tasks import instruction_text

    out.mkdir(parents=True, exist_ok=True)
    proc, url = start_plumberbench(seed, level, facts, out)
    started = time.time()
    try:
        run = asyncio.run(play(provider, url, instruction_text(facts, level), max_turns, out / "transcript.jsonl"))
    finally:
        proc.kill()
    result = json.loads((out / "server" / "result.json").read_text())
    summary = {"seed": seed, "level": level, "mode": "facts" if facts else "pictures only",
               "score": result["score"], "repair": result["repair"],
               "faults": f"{result['faults_fixed']}/{result['faults_total']}", "damage": result["damage"],
               "time": f"{result['time_used']}/{result['time_budget']}", "steps": result["steps"],
               "free_actions": result.get("free_actions"), "diagnosis_correct": result["diagnosis_correct"],
               "finished": result["finished"], "stop": run["stop"], "turns": run["turns"],
               "tool_calls": run["tool_calls"], "usage": run["usage"], "seconds": round(time.time() - started, 1)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "replay.html").write_text(build(out / "server"))
    return summary


def seed_list(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def table(rows: list[dict]) -> str:
    head = "| Level | Seed | Mode | Score | Faults | Damage | Time | Free | Diagnosis | Stop | Calls |"
    lines = [head, "|" + "---|" * 11]
    for r in rows:
        lines.append(f"| {r['level']} | {r['seed']} | {r['mode']} | {r['score']:.2f} | {r['faults']} | "
                     f"{r['damage']} | {r['time']} | {r['free_actions']} | "
                     f"{'right' if r['diagnosis_correct'] else 'wrong'} | {r['stop']} | {r['tool_calls']} |")
    by_level: dict = {}
    for r in rows:
        by_level.setdefault((r["level"], r["mode"]), []).append(r["score"])
    lines += ["", "| Level | Mode | Mean score | Runs |", "|---|---|---|---|"]
    lines += [f"| {lv} | {mode} | {statistics.mean(s):.2f} | {len(s)} |" for (lv, mode), s in sorted(by_level.items())]
    used = {k: sum(r["usage"].get(k, 0) for r in rows) for k in ("input", "output", "cache_read", "cache_write")}
    lines += ["", "Tokens: " + ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in used.items())]
    return "\n".join(lines)


def cmd_run(args) -> int:
    root = Path(args.out) / f"{args.provider}-{(args.model or 'default').replace('/', '_')}-{time.strftime('%Y%m%d-%H%M%S')}"
    rows, any_calls, stopped = [], False, False
    grid = [(mode, level, seed) for mode in args.mode for level in args.levels for seed in seed_list(args.seeds)]
    for mode, level, seed in grid:
        provider = make_provider(args)
        out = root / f"l{level}-s{seed:03d}-{mode}"
        print(f"level {level}, house {seed}, {mode} ...", flush=True)
        try:
            r = episode(provider, seed, level, mode == "facts", out, args.max_turns)
        except Exception as e:  # keep going; record the failure
            print(f"  failed: {e}", flush=True)
            r = None
        if r is not None:
            rows.append(r)
            print(f"  score {r['score']:.2f}, faults {r['faults']}, {r['tool_calls']} calls, stop: {r['stop']}",
                  flush=True)
            any_calls = any_calls or r["tool_calls"] > 0
        if not any_calls and (r is None or r["stop"].startswith("codex failed")):
            # Nothing has worked yet and this failed before a single tool call (a bad model name,
            # key or sign-in): the other jobs would fail the same way.
            print("Stopping: the first job failed before any tool call, so the rest would too.", flush=True)
            stopped = True
            break
    if rows:
        report = table(rows)
        root.mkdir(parents=True, exist_ok=True)
        (root / "summary.md").write_text(report + "\n")
        (root / "summary.json").write_text(json.dumps(rows, indent=2))
        print("\n" + report + f"\n\nRuns, transcripts and replay pages: {root}")
    return 1 if stopped or not rows else 0


# ------------------------------------------------------------------ smoke

def smoke_verdict(answer: str, shown: list[str]) -> str:
    digits = "".join(ch for ch in answer if ch.isdigit())
    if not digits or not shown:
        return "NO ANSWER"
    if len(shown) != 5:
        return f"CALLS: show_number was called {len(shown)} times, not 5"
    if digits == shown[4]:
        return "PASS"
    if digits in shown[:4]:
        return f"STALE: matches call {shown.index(digits) + 1}"
    return "BLIND: matches no number shown"


def smoke_once(provider, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    proc = start_process([sys.executable, str(SMOKE_SERVER)],
                         {"SMOKE_LOG_DIR": str(out / "server"), "PORT": str(port)},
                         f"http://127.0.0.1:{port}/health", out / "server.log")
    try:
        run = asyncio.run(play(provider, f"http://127.0.0.1:{port}/mcp", SMOKE_TASK, 12, out / "transcript.jsonl"))
    finally:
        proc.kill()
    shown_file = out / "server" / "shown.json"
    shown = json.loads(shown_file.read_text()) if shown_file.exists() else []
    verdict = smoke_verdict(run["final"], shown)
    (out / "verdict.json").write_text(json.dumps({"verdict": verdict, "answer": run["final"], "shown": shown}, indent=2))
    return {"verdict": verdict, "answer": run["final"].strip(), "shown": shown}


def cmd_smoke(args) -> int:
    root = Path(args.out) / f"smoke-{args.provider}-{(args.model or 'default').replace('/', '_')}-{time.strftime('%Y%m%d-%H%M%S')}"
    passed = 0
    for i in range(1, args.repeat + 1):
        r = smoke_once(make_provider(args), root / f"run{i}")
        passed += r["verdict"] == "PASS"
        print(f"run {i}: {r['verdict']}  (answer {r['answer']!r}, shown {r['shown']})", flush=True)
    print(f"{passed}/{args.repeat} passed. Logs: {root}")
    return 0 if passed == args.repeat else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a model on PlumberBench locally, through the MCP server.")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("run", "smoke"):
        p = sub.add_parser(name)
        p.add_argument("--provider", choices=("anthropic", "openai", "openai-agents", "codex"), required=True)
        p.add_argument("--model", help="required, except for codex (which then uses its default model)")
        p.add_argument("--base-url", help="API base URL (for OpenAI-compatible endpoints other than OpenAI)")
        p.add_argument("--key-env", help="environment variable holding the API key")
        p.add_argument("--max-tokens", type=int, default=16000,
                       help="output tokens per model turn, thinking included (a cap: only what is used is billed)")
        p.add_argument("--reasoning-effort", help="OpenAI providers and codex: e.g. none, low, medium, high")
        p.add_argument("--out", default="runs")
        if name == "run":
            p.add_argument("--levels", type=int, nargs="+", default=[1])
            p.add_argument("--seeds", default="0", help="e.g. 0-4 or 0,3,7")
            p.add_argument("--mode", nargs="+", choices=("facts", "vision"), default=["facts"])
            p.add_argument("--max-turns", type=int, default=400)
        else:
            p.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    return cmd_run(args) if args.command == "run" else cmd_smoke(args)


if __name__ == "__main__":
    raise SystemExit(main())
