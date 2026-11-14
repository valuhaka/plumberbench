"""The local runner: real adapters and the real MCP server, with the model replaced by a script.

No API keys are used. A fake HTTP layer answers each request with the next of
the reference solver's moves, so a run must reproduce the reference score, and
the requests each provider would receive can be inspected.
"""
import base64
import io
import json
from pathlib import Path

import pytest

from plumberbench import agent
from plumberbench.env import Episode
from plumberbench.solver import Solver

SEED, LEVEL = 5, 1


def reference_moves(seed=SEED, level=LEVEL):
    ep = Episode(seed, level, render=False)
    Solver(lambda tool, args: ep.act(tool, **args).text).run()
    return ep.actions, ep.result()["score"]


def fake_model(moves, kind, requests):
    """A post_json stand-in that plays `moves`, one per request, in the provider's own format."""
    i = {"n": 0}

    def post(url, headers, body, timeout=300):
        requests.append(json.loads(json.dumps(body)))
        n = i["n"]
        i["n"] += 1
        if kind == "anthropic":
            if n >= len(moves):
                return {"content": [{"type": "text", "text": "All done."}], "usage": {"input_tokens": 1}}
            tool, args = moves[n]
            return {"content": [{"type": "tool_use", "id": f"t{n}", "name": tool, "input": args}],
                    "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}}
        if n >= len(moves):
            return {"choices": [{"message": {"role": "assistant", "content": "All done."}}], "usage": {}}
        tool, args = moves[n]
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{n}", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 40}}}
    return post


@pytest.mark.parametrize("kind", ["anthropic", "openai"])
def test_a_run_through_each_adapter_reproduces_the_reference(tmp_path, monkeypatch, kind):
    moves, want = reference_moves()
    requests = []
    monkeypatch.setattr(agent, "post_json", fake_model(moves, kind, requests))
    provider = (agent.Anthropic if kind == "anthropic" else agent.OpenAICompatible)("test-model", "key")
    summary = agent.episode(provider, SEED, LEVEL, facts=False, out=tmp_path, max_turns=200)
    assert summary["score"] == want > 0.9
    assert summary["stop"] == "job over" and summary["tool_calls"] == len(moves)
    assert (tmp_path / "replay.html").exists() and (tmp_path / "transcript.jsonl").exists()

    last = requests[-1]
    answered = len(moves) - 1  # the last request precedes `finish`, whose result ends the run
    if kind == "anthropic":
        msgs = last["messages"]
        tool_results = [b for m in msgs if m["role"] == "user" for b in m["content"] if b["type"] == "tool_result"]
        assert len(tool_results) == answered
        pictures = [c for b in tool_results for c in b["content"] if c["type"] == "image"]
        assert pictures and all(c["source"]["media_type"] == "image/jpeg" for c in pictures)
        assert 0 < len(pictures) < answered, "unchanged views send no picture"
        cached = [b for m in msgs for b in m["content"] if isinstance(b, dict) and "cache_control" in b]
        assert cached == [msgs[-1]["content"][-1]], "exactly one rolling breakpoint, on the latest block"
        assert "cache_control" in last["system"][0] and "cache_control" in last["tools"][-1]
        assert {t["name"] for t in last["tools"]} >= {"look", "inspect", "finish"}
        assert summary["usage"]["cache_read"] == 100 * len(moves)
    else:
        msgs = last["messages"]
        assert sum(m["role"] == "tool" for m in msgs) == answered
        follow = [m for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
        assert follow and all(p["image_url"]["url"].startswith("data:image/jpeg;base64,")
                              for m in follow for p in m["content"] if p["type"] == "image_url")
        assert last["tools"][0]["type"] == "function"
    assert "Fix the plumbing" in json.dumps(requests[0])


def test_the_instruction_matches_the_mode(tmp_path, monkeypatch):
    requests = []
    monkeypatch.setattr(agent, "post_json", fake_model([("finish", {"diagnosis": []})], "anthropic", requests))
    agent.episode(agent.Anthropic("m", "k"), SEED, LEVEL, facts=True, out=tmp_path, max_turns=5)
    task = requests[0]["messages"][0]["content"][0]["text"]
    assert "FACTS:" in task


def test_smoke_mode_tells_pass_from_stale(tmp_path):
    """The pictures reach the 'model': a reader that decodes them passes; one that keeps the first is stale."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "read_number", agent.ROOT / "harbor" / "smoke-vision" / "solution" / "read_number.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    decode = lambda res: reader.read(base64.b64decode(res.images[0][1])) if res.images else None

    fresh = agent.Scripted([("show_number", {})] * 5, reader=decode)
    assert agent.smoke_once(fresh, tmp_path / "fresh")["verdict"] == "PASS"
    assert all(len(r.images) == 1 for r in fresh.seen)

    first = {}
    keep_first = lambda res: first.setdefault("n", decode(res))
    stale = agent.Scripted([("show_number", {})] * 5, reader=keep_first)
    assert agent.smoke_once(stale, tmp_path / "stale")["verdict"].startswith("STALE")


def test_verdicts():
    shown = ["111111", "222222", "333333", "444444", "555555"]
    assert agent.smoke_verdict("555555", shown) == "PASS"
    assert agent.smoke_verdict("The number is 222222.", shown).startswith("STALE")
    assert agent.smoke_verdict("999999", shown).startswith("BLIND")
    assert agent.smoke_verdict("", shown) == "NO ANSWER"
    assert agent.smoke_verdict("555555", shown[:3]).startswith("CALLS")


def test_reasoning_effort_is_sent_only_when_asked():
    plain = agent.OpenAICompatible("m", "key")
    plain.start("system", "task", [])
    assert "reasoning_effort" not in plain.request()
    off = agent.OpenAICompatible("m", "key", reasoning_effort="none")
    off.start("system", "task", [])
    assert off.request()["reasoning_effort"] == "none"


class SDKModel:
    """An Agents SDK model that plays `moves`, one per request, and records what it is sent."""

    def __init__(self, moves):
        from agents.models.interface import Model
        self.moves, self.n, self.inputs = moves, 0, []
        outer = self

        class _M(Model):
            async def get_response(self, system_instructions, input, model_settings, tools, output_schema,
                                   handoffs, tracing, **kw):
                return outer.respond(input, model_settings)

            def stream_response(self, *a, **kw):
                raise NotImplementedError

        self.model = _M()

    def respond(self, input, settings):
        from agents.items import ModelResponse
        from agents.usage import Usage
        from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
        self.inputs.append(json.loads(json.dumps(input, default=str)))
        self.settings = settings
        n, self.n = self.n, self.n + 1
        if n >= len(self.moves):
            out = [ResponseOutputMessage(id=f"m{n}", type="message", role="assistant", status="completed",
                                         content=[ResponseOutputText(type="output_text", text="All done.",
                                                                     annotations=[])])]
        else:
            tool, args = self.moves[n]
            out = [ResponseFunctionToolCall(type="function_call", id=f"fc{n}", call_id=f"c{n}", name=tool,
                                            arguments=json.dumps(args), status="completed")]
        return ModelResponse(output=out, usage=Usage(requests=1, input_tokens=10, output_tokens=5,
                                                     total_tokens=15), response_id=None)


def test_a_run_through_the_agents_sdk_reproduces_the_reference_and_shows_the_pictures(tmp_path):
    pytest.importorskip("agents")
    from plumberbench.agents_sdk import AgentsSDK
    moves, want = reference_moves()
    fake = SDKModel(moves)
    provider = AgentsSDK("test-model", "key", reasoning_effort="low", model_obj=fake.model)
    summary = agent.episode(provider, SEED, LEVEL, facts=False, out=tmp_path, max_turns=200)
    assert summary["score"] == want > 0.9
    assert summary["stop"] == "job over" and summary["tool_calls"] == len(moves)
    assert fake.settings.parallel_tool_calls is False and fake.settings.reasoning.effort == "low"
    last = json.dumps(fake.inputs[-1])
    assert '"input_image"' in last and "data:image/jpeg;base64," in last
    lines = [json.loads(x) for x in (tmp_path / "transcript.jsonl").read_text().splitlines()]
    assert sum("tool" in x for x in lines) == len(moves) and any(x.get("pictures") for x in lines)
