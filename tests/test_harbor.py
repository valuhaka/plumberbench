"""The live MCP server and the generated Harbor tasks, end to end on this machine."""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from live import SRC, start_server

from plumberbench.env import Episode
from plumberbench.solver import Solver
from plumberbench.tasks import write_task

@pytest.mark.parametrize("facts", ["1", "0"])
def test_reference_solver_over_mcp(tmp_path, facts):
    """Same score through the server as in process, with FACTS in the text or via the token route."""
    proc, port = start_server(tmp_path, PB_SEED="11", PB_LEVEL="3", PB_FACTS=facts,
                              PB_SOLVER_TOKEN="t0ken", PB_RENDER="0")
    try:
        cmd = [sys.executable, str(SRC / "plumberbench" / "solver.py"), f"http://127.0.0.1:{port}/mcp"]
        if facts == "0":
            cmd.append(f"http://127.0.0.1:{port}/facts?token=t0ken")
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/facts?token=guess", timeout=2)
    finally:
        proc.kill()
    live = json.loads((tmp_path / "log" / "result.json").read_text())
    ep = Episode(11, 3, render=False)
    Solver(lambda tool, args: ep.act(tool, **args).text).run()
    assert live["score"] == ep.result()["score"] > 0.9


def test_task_toml_collects_the_episode_log_from_the_sidecar(tmp_path):
    """The artifacts list must be a top-level key: under a [table] header TOML files it in that
    table, Harbor never collects the log, and every run scores the untouched house."""
    import tomllib
    for mode in ("facts", "vision"):
        cfg = tomllib.loads((write_task(tmp_path / mode, level=1, seed=0, mode=mode) / "task.toml").read_text())
        assert cfg["artifacts"] == [{"source": "/var/plumberbench", "service": "mcp-server"}]
        assert "artifacts" not in cfg.get("metadata", {})
        assert cfg["verifier"]["environment_mode"] == "separate"
        assert cfg["environment"]["mcp_servers"][0]["url"] == "http://mcp-server:8000/mcp"
    smoke = tomllib.loads((Path(__file__).resolve().parents[1] / "harbor" / "smoke-vision" / "task.toml").read_text())
    assert {a.get("service") for a in smoke["artifacts"]} == {None, "mcp-server"}


def test_generated_task_verifier_replays_the_log(tmp_path):
    task = write_task(tmp_path / "tasks", level=2, seed=4, mode="vision")
    compose = (task / "environment" / "docker-compose.yaml").read_text()
    assert 'PB_FACTS: "0"' in compose and 'PB_SEED: "4"' in compose
    token = compose.split('PB_SOLVER_TOKEN: "')[1].split('"')[0]
    assert token and token in (task / "solution" / "solve.sh").read_text()
    assert token not in (task / "instruction.md").read_text()
    assert "FACTS" not in (task / "instruction.md").read_text()

    log = tmp_path / "var"
    ep = Episode(4, 2, facts=False, render=False, log_dir=log)
    Solver(lambda tool, args: ep.act(tool, **args).text,
           facts_source=lambda: __import__("plumberbench.observe", fromlist=["facts"]).facts(ep.state)).run()
    expected = ep.result()["score"]

    out = tmp_path / "verifier"
    env = {**os.environ, "PB_LOG_DIR": str(log), "PB_VERIFIER_OUT": str(out)}
    env.pop("PYTHONPATH", None)
    subprocess.run([sys.executable, "-I", str(task / "tests" / "verify.py")], env=env, check=True,
                   capture_output=True, timeout=60)
    assert float((out / "reward.txt").read_text()) == expected > 0.9

    # A log edited to claim more is ignored: the verifier replays actions, not results.
    (log / "result.json").write_text(json.dumps({"score": 1.0}))
    rows = (log / "episode.jsonl").read_text().splitlines()
    (log / "episode.jsonl").write_text("\n".join(rows[:3]) + "\n")
    subprocess.run([sys.executable, "-I", str(task / "tests" / "verify.py")], env=env, check=True,
                   capture_output=True, timeout=60)
    assert float((out / "reward.txt").read_text()) == 0.0


def test_missing_log_scores_zero(tmp_path):
    task = write_task(tmp_path / "tasks", level=1, seed=0, mode="facts")
    out = tmp_path / "verifier"
    env = {**os.environ, "PB_LOG_DIR": str(tmp_path / "nothing"), "PB_VERIFIER_OUT": str(out)}
    subprocess.run([sys.executable, "-I", str(task / "tests" / "verify.py")], env=env, check=True,
                   capture_output=True, timeout=60)
    assert float((out / "reward.txt").read_text()) == 0.0
