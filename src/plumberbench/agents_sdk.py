"""The OpenAI Agents SDK as a provider for the local runner (`--provider openai-agents`).

The SDK runs its own agent loop over the Responses API, so reasoning stays on
while the model calls tools, and it hands the MCP server's pictures to the
model inside the tool results. The runner still starts the server, keeps the
logs and builds the replay and summary, so these runs compare with the others.

Calls go one at a time (parallel tool calls off), as the house is one place.
The run ends when a tool result says the job is over, when the model stops
calling tools, or at --max-turns. Traces appear in the OpenAI dashboard under
the workflow name "PlumberBench", unless the endpoint is not OpenAI's.

Needs the `agents` extra:  uv run --extra agents -m plumberbench.agent ...
"""
from __future__ import annotations

import json
from pathlib import Path

JOB_OVER = "The job is over"


def _items(output) -> list:
    return output if isinstance(output, list) else [output]


def _field(item, name: str):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def output_text(output) -> str:
    """The text of a tool output as the SDK keeps it: a string, or text and image parts."""
    return "\n".join(t for t in (item if isinstance(item, str) else _field(item, "text") or ""
                                 for item in _items(output)) if t)


def output_pictures(output) -> int:
    return sum(1 for item in _items(output) if not isinstance(item, str) and _field(item, "type") == "image")


class AgentsSDK:
    """Plays a whole episode through the OpenAI Agents SDK; see the module docstring."""

    def __init__(self, model: str, key: str, base_url: str | None = None, max_tokens: int = 16000,
                 reasoning_effort: str | None = None, model_obj=None, tracing: bool = True):
        self.model, self.key, self.base_url = model, key, base_url
        self.max_tokens, self.reasoning_effort = max_tokens, reasoning_effort
        self.model_obj = model_obj  # a ready agents Model, for tests
        self.tracing = tracing and base_url is None and model_obj is None
        self.over = False

    def _model(self):
        if self.model_obj is not None:
            return self.model_obj
        from agents import OpenAIResponsesModel
        from openai import AsyncOpenAI
        return OpenAIResponsesModel(model=self.model, openai_client=AsyncOpenAI(api_key=self.key, base_url=self.base_url))

    def _stop_when_job_over(self, context, results):
        from agents.agent import ToolsToFinalOutputResult
        for r in results:
            text = output_text(r.output)
            if JOB_OVER in text:
                self.over = True
                return ToolsToFinalOutputResult(is_final_output=True, final_output=text)
        return ToolsToFinalOutputResult(is_final_output=False)

    async def play(self, url: str, task: str, max_turns: int, transcript: Path, system: str) -> dict:
        from agents import Agent, ItemHelpers, ModelSettings, RunConfig, Runner, set_tracing_export_api_key
        from agents.exceptions import MaxTurnsExceeded
        from agents.items import MessageOutputItem, ToolCallItem, ToolCallOutputItem
        from agents.mcp import MCPServerStreamableHttp
        from openai.types.shared import Reasoning

        if self.tracing:
            set_tracing_export_api_key(self.key)
        settings = ModelSettings(parallel_tool_calls=False, max_tokens=self.max_tokens,
                                 reasoning=Reasoning(effort=self.reasoning_effort) if self.reasoning_effort else None)
        self.over = False
        stop, final, items, usage = "model stopped", "", [], None
        async with MCPServerStreamableHttp(params={"url": url, "timeout": 60, "sse_read_timeout": 600},
                                           name="plumberbench", cache_tools_list=True,
                                           client_session_timeout_seconds=600) as server:
            init = server.server_initialize_result
            instructions = getattr(init, "instructions", None) or ""
            agent = Agent(name="plumber", instructions=system + ("\n\n" + instructions if instructions else ""),
                          mcp_servers=[server], model=self._model(), model_settings=settings,
                          tool_use_behavior=self._stop_when_job_over)
            run_config = RunConfig(workflow_name="PlumberBench", tracing_disabled=not self.tracing)
            try:
                result = await Runner.run(agent, task, max_turns=max_turns, run_config=run_config)
                items, usage, final = result.new_items, result.context_wrapper.usage, str(result.final_output or "")
            except MaxTurnsExceeded as e:
                stop = "max turns"
                if e.run_data is not None:
                    items, usage = e.run_data.new_items, e.run_data.context_wrapper.usage
        if self.over:
            stop = "job over"

        calls = 0
        with transcript.open("w") as log:
            for item in items:
                if isinstance(item, ToolCallItem):
                    calls += 1
                    raw = item.raw_item
                    try:
                        args = json.loads(_field(raw, "arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {"_unparsed": _field(raw, "arguments")}
                    log.write(json.dumps({"tool": _field(raw, "name"), "args": args}) + "\n")
                elif isinstance(item, ToolCallOutputItem):
                    log.write(json.dumps({"result": output_text(item.output),
                                          "pictures": output_pictures(item.output)}) + "\n")
                elif isinstance(item, MessageOutputItem):
                    log.write(json.dumps({"text": ItemHelpers.text_message_output(item)}) + "\n")
        cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        return {"turns": getattr(usage, "requests", 0) or 0, "tool_calls": calls, "stop": stop, "final": final,
                "usage": {"input": (getattr(usage, "input_tokens", 0) or 0) - cached,
                          "output": getattr(usage, "output_tokens", 0) or 0, "cache_read": cached, "cache_write": 0}}
