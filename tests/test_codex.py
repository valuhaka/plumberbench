"""The codex provider: the real `codex exec` and the real MCP server, with a fake model.

tests/fake_responses.py stands in for the OpenAI Responses API and plays the
reference plumber's moves, so a run must reproduce the reference score. It
also keeps every request, to check what Codex sends the model: the pictures as
images, and no shell. Codex runs with a throwaway CODEX_HOME, so your own
sign-in and settings are never touched. Skipped if Codex is not installed
(PB_CODEX can point at the binary).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from plumberbench import agent
from plumberbench.codex_cli import CodexCLI, command, find_codex
from plumberbench.env import Episode
from plumberbench.solver import Solver

SEED, LEVEL = 5, 1
FAKE = Path(__file__).with_name("fake_responses.py")


def test_the_command_locks_codex_to_the_house(tmp_path):
    cmd = command("codex", "http://127.0.0.1:1/mcp", "prompt", tmp_path, "m", "low")
    text = " ".join(cmd)
    for feature in ("shell_tool", "multi_agent", "image_generation", "goals"):
        assert f"--disable {feature}" in text
    for part in ("--sandbox read-only", "--ignore-user-config", "--ephemeral", 'web_search="disabled"',
                 'mcp_servers.plumberbench.default_tools_approval_mode="approve"',
                 "mcp_servers.plumberbench.supports_parallel_tool_calls=false", 'model_reasoning_effort="low"'):
        assert part in text
    assert cmd[-1] == "prompt"


@pytest.mark.skipif(not find_codex(), reason="Codex is not installed (npm install -g @openai/codex)")
def test_a_run_through_codex_reproduces_the_reference_and_shows_the_pictures(tmp_path):
    ep = Episode(SEED, LEVEL, render=False)
    Solver(lambda tool, args: ep.act(tool, **args).text).run()
    moves, want = ep.actions, ep.result()["score"]
    (tmp_path / "moves.json").write_text(json.dumps(moves))
    port = agent.free_port()
    fake = subprocess.Popen([sys.executable, str(FAKE), str(port), str(tmp_path / "moves.json"),
                             str(tmp_path / "requests")])
    try:
        time.sleep(0.5)
        provider = CodexCLI("fake-model", extra=(
            "-c", 'model_provider="fake"', "-c", 'model_providers.fake.name="fake"',
            "-c", f'model_providers.fake.base_url="http://127.0.0.1:{port}/v1"',
            "-c", 'model_providers.fake.env_key="FAKE_KEY"', "-c", 'model_providers.fake.wire_api="responses"'),
            env={"CODEX_HOME": str(tmp_path / "codex-home"), "FAKE_KEY": "x"})
        (tmp_path / "codex-home").mkdir()
        summary = agent.episode(provider, SEED, LEVEL, facts=False, out=tmp_path / "ep", max_turns=200)
    finally:
        fake.kill()
    assert summary["score"] == want > 0.9
    assert summary["stop"] == "job over" and summary["tool_calls"] == len(moves)
    last = json.loads(sorted((tmp_path / "requests").glob("req_*.json"))[-1].read_text())
    outputs = [i for i in last["input"] if i.get("type") == "function_call_output"]
    assert len(outputs) == len(moves)
    assert any("input_image" in json.dumps(o) and "data:image/jpeg;base64," in json.dumps(o) for o in outputs)
    names = [t.get("name", "") for t in last["tools"]]
    assert "mcp__plumberbench" in names
    assert not [n for n in names if "shell" in n or "exec" in n], names
