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
    """Same score through the server as in process: with FACTS in the text, or, in pictures-only
    mode, from the solver's own copy of the house (--twin), which must track the server exactly."""
    proc, port = start_server(tmp_path, PB_SEED="11", PB_LEVEL="3", PB_FACTS=facts, PB_RENDER="0")
    try:
        cmd = [sys.executable, str(SRC / "plumberbench" / "solver.py"), f"http://127.0.0.1:{port}/mcp"]
        if facts == "0":
            cmd += ["--twin", "11", "3"]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        with pytest.raises(urllib.error.HTTPError):  # no hidden route left on the server
            urllib.request.urlopen(f"http://127.0.0.1:{port}/facts", timeout=2)
    finally:
        proc.kill()
    live = json.loads((tmp_path / "log" / "result.json").read_text())
    ep = Episode(11, 3, render=False)
    Solver(lambda tool, args: ep.act(tool, **args).text).run()
    assert live["score"] == ep.result()["score"] > 0.9


def test_a_drifting_copy_of_the_house_stops_the_solver(tmp_path):
    """The wrong seed for --twin makes the copy disagree with the server; the solver must stop
    rather than play on with facts about another house."""
    proc, port = start_server(tmp_path, PB_SEED="11", PB_LEVEL="3", PB_FACTS="0", PB_RENDER="0")
    try:
        r = subprocess.run([sys.executable, str(SRC / "plumberbench" / "solver.py"),
                            f"http://127.0.0.1:{port}/mcp", "--twin", "12", "3"],
                           capture_output=True, text=True, timeout=120)
    finally:
        proc.kill()
    assert r.returncode != 0 and "drifted" in r.stderr


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
    assert "TOKEN" not in compose and "/facts" not in (task / "solution" / "solve.sh").read_text()
    assert "--twin 4 2" in (task / "solution" / "solve.sh").read_text()
    assert "FACTS" not in (task / "instruction.md").read_text()

    # The oracle exactly as generated: solution/solver.py with its own copy of the simulator.
    proc, port = start_server(tmp_path / "live", PB_SEED="4", PB_LEVEL="2", PB_FACTS="0", PB_RENDER="0")
    try:
        subprocess.run([sys.executable, "-I", str(task / "solution" / "solver.py"),
                        f"http://127.0.0.1:{port}/mcp", "--twin", "4", "2"], check=True,
                       capture_output=True, timeout=120)
    finally:
        proc.kill()
    oracle = json.loads((tmp_path / "live" / "log" / "result.json").read_text())["score"]

    log = tmp_path / "var"
    ep = Episode(4, 2, facts=False, render=False, log_dir=log)
    Solver(lambda tool, args: ep.act(tool, **args).text,
           facts_source=lambda: __import__("plumberbench.observe", fromlist=["facts"]).facts(ep.state)).run()
    expected = ep.result()["score"]
    assert oracle == expected

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


def test_committed_tasks_and_registry_are_up_to_date():
    """Harbor runs the committed folders (harbor run --repo ...), so they must match what the code
    generates now. If this fails: python -m plumberbench.tasks, then commit."""
    from plumberbench.generate import LEVELS
    from plumberbench.tasks import check
    root = Path(__file__).resolve().parents[1]
    assert check(root / "harbor" / "tasks", root / "registry.json", list(LEVELS), list(range(10)),
                 ["facts", "vision"]) == []


def test_registry_lists_every_task_folder_once():
    root = Path(__file__).resolve().parents[1]
    reg = json.loads((root / "registry.json").read_text())
    by_name = {d["name"]: d for d in reg}
    assert set(by_name) == {"plumberbench", "plumberbench-vision", "plumberbench-facts", "plumberbench-smoke"}
    for d in reg:
        assert d["version"] and d["description"] and d["tasks"]
        for t in d["tasks"]:
            assert (root / t["path"] / "task.toml").is_file(), t
            assert "git_url" not in t  # Harbor fills the repo and commit in from --repo
    every = {t["name"] for t in by_name["plumberbench"]["tasks"]}
    assert every == {p.name for p in (root / "harbor" / "tasks").iterdir() if p.is_dir()}
    assert every == {t["name"] for t in by_name["plumberbench-vision"]["tasks"]} | \
        {t["name"] for t in by_name["plumberbench-facts"]["tasks"]}


def test_private_tasks_do_not_carry_their_seed_in_the_name(tmp_path):
    """Container names come from task names, and an agent can often look its own up."""
    from plumberbench.tasks import write_private
    write_private(tmp_path, levels=[3], n=2, modes=["vision"])
    seeds = json.loads((tmp_path / "seeds.json").read_text())
    assert sorted(seeds) == ["l3-p00-vision", "l3-p01-vision"]
    for name, seed in seeds.items():
        assert str(seed) not in name and seed >= 10**8
        assert f'PB_SEED: "{seed}"' in (tmp_path / name / "environment" / "docker-compose.yaml").read_text()
        assert str(seed) not in (tmp_path / name / "environment" / "Dockerfile").read_text()
