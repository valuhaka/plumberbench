"""Write Harbor task folders, one per (level, seed, mode).

    python -m plumberbench.tasks --out harbor/tasks --levels 1 2 3 4 --seeds 0-9 --mode facts vision

Modes:
    facts   every response has the picture and a FACTS list of what it shows
    vision  pictures and sounds only; the reference solver reads FACTS through
            a token-protected route that the agent never learns

Each folder:
    instruction.md, task.toml
    environment/Dockerfile                agent container (nothing to find in it)
    environment/docker-compose.yaml       adds the mcp-server sidecar
    environment/mcp-server/               the simulator, renderer and MCP server
    solution/solve.sh, solution/solver.py the scripted reference plumber (oracle)
    tests/Dockerfile, tests/test.sh       separate verifier: replays the logged
    tests/verify.py, tests/plumberbench/  actions and scores the end state
"""
from __future__ import annotations

import argparse
import secrets
import shutil
from pathlib import Path

from .generate import LEVELS
from .world import DIAGNOSES, DIAGNOSIS_TEXT

PKG = Path(__file__).parent
SERVER_FILES = ["__init__.py", "world.py", "sim.py", "layout.py", "generate.py", "judge.py", "observe.py",
                "env.py", "scene.py", "render.py", "server.py"]
JUDGE_FILES = ["__init__.py", "world.py", "sim.py", "layout.py", "generate.py", "judge.py"]

PINS = "mujoco==4.0.1 pillow==12.3.0 numpy==2.5.3 fastmcp==4.2.0"

FACTS_NOTE = """- Each response also ends with a `FACTS:` section: a JSON list of what the view shows,
  following the same visibility rules as the picture (you cannot see inside a pipe that is closed).
"""

TASK_TOML = """schema_version = "1.1"

# Everything the judge needs lives in the simulator sidecar, out of the agent's reach.
# This must stay above the first [table]: below one, TOML files it under that table.
artifacts = [{{ source = "/var/plumberbench", service = "mcp-server" }}]

[task]
name = "plumberbench/{name}"
description = "Diagnose and repair a household plumbing fault through a rendered 3D view (level {level}, seed {seed}, {mode} mode)."
authors = []
keywords = ["plumberbench", "vision", "world-model", "diagnosis", "mcp"]

[metadata]
difficulty = "{difficulty}"
category = "agentic"
tags = ["mcp", "vision", "sidecar", "separate-verifier"]

[verifier]
timeout_sec = 180.0
environment_mode = "separate"

[agent]
timeout_sec = 2400.0

[environment]
build_timeout_sec = 1800.0
cpus = 2
memory_mb = 4096
storage_mb = 10240
gpus = 0

[[environment.mcp_servers]]
name = "plumberbench"
transport = "streamable-http"
url = "http://mcp-server:8000/mcp"
args = []
"""

COMPOSE = """# Merged on top of Harbor's base compose config; `main` is configured by Harbor.
services:
  main:
    depends_on:
      mcp-server:
        condition: service_healthy

  mcp-server:
    build:
      context: ./mcp-server
    environment:
      PB_SEED: "{seed}"
      PB_LEVEL: "{level}"
      PB_FACTS: "{facts}"
      PB_RENDER: "1"
      PB_LOG_DIR: /var/plumberbench
      PB_SOLVER_TOKEN: "{token}"
    expose:
      - "8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"]
      interval: 2s
      timeout: 5s
      retries: 30
      start_period: 10s
"""

MAIN_DOCKERFILE = """FROM ubuntu:24.04

RUN apt-get update && apt-get install -y curl python3 python3-pip \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
"""

SERVER_DOCKERFILE = f"""FROM python:3.13-slim

# Headless OpenGL through EGL (Mesa, CPU only) and a font for the tags.
RUN apt-get update && apt-get install -y --no-install-recommends \\
        libegl1 libegl-mesa0 libgl1 libgl1-mesa-dri libgbm1 libglvnd0 fonts-dejavu-core \\
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir {PINS}

ENV MUJOCO_GL=egl PYTHONPATH=/app PYTHONUNBUFFERED=1
WORKDIR /app
COPY plumberbench /app/plumberbench
EXPOSE 8000
CMD ["python", "-m", "plumberbench.server"]
"""

SOLVE_SH = """#!/bin/bash
# Oracle: the scripted reference plumber, playing through the same MCP tools as the agent.
set -euo pipefail
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv run --with mcp python3 /solution/solver.py http://mcp-server:8000/mcp {facts_arg}
"""

TESTS_DOCKERFILE = """# Separate verifier image. Sidecar artifacts reappear at /var/plumberbench.
FROM python:3.13-slim
COPY . /tests/
"""

TEST_SH = """#!/bin/bash
set -uo pipefail
python3 /tests/verify.py
"""

VERIFY_PY = '''"""Score the episode: replay the logged actions from the seed and judge the end state.

The replay is the source of truth. The server's own result.json is only
cross-checked against it, so a damaged or missing file cannot raise the score.
Paths can be overridden (PB_LOG_DIR, PB_VERIFIER_OUT) to run this outside Harbor.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plumberbench.judge import replay, score  # noqa: E402

SEED, LEVEL = {seed}, {level}
LOG = Path(os.environ.get("PB_LOG_DIR", "/var/plumberbench"))
OUT = Path(os.environ.get("PB_VERIFIER_OUT", "/logs/verifier"))
OUT.mkdir(parents=True, exist_ok=True)

rows = []
episode = LOG / "episode.jsonl"
if episode.exists():
    rows = [json.loads(line) for line in episode.read_text().splitlines() if line.strip()]
else:
    print("No episode log was collected from the sidecar: scoring the untouched house.")

state = replay(SEED, LEVEL, [(r["tool"], r["args"]) for r in rows])
result = score(state)
result.update(seed=SEED, level=LEVEL, steps=len(rows))

logged = LOG / "result.json"
if logged.exists():
    live = json.loads(logged.read_text()).get("score")
    result["live_score"] = live
    if live is not None and abs(live - result["score"]) > 1e-9:
        print(f"WARNING: live score {{live}} differs from replayed score {{result['score']}}")

(OUT / "details.json").write_text(json.dumps(result, indent=2))
(OUT / "reward.txt").write_text(str(result["score"]))
print(json.dumps({{k: result[k] for k in ("score", "repair", "faults_fixed", "faults_total",
                                         "damage", "time_used", "time_budget", "diagnosis_correct",
                                         "left_worse")}}, indent=2))
'''

DIFFICULTY = {1: "easy", 2: "medium", 3: "hard", 4: "hard"}


def instruction_text(facts: bool) -> str:
    """The task instruction the agent gets, for facts or pictures-only mode."""
    text = (PKG / "instruction.md").read_text()
    text = text.replace("{facts_note}", FACTS_NOTE if facts else "")
    return text.replace("{diagnoses}", "\n".join(f"- `{d}`: {DIAGNOSIS_TEXT[d]}." for d in DIAGNOSES))


def task_name(level: int, seed: int, mode: str) -> str:
    return f"l{level}-s{seed:03d}-{mode}"


def write_task(root: Path, level: int, seed: int, mode: str) -> Path:
    name = task_name(level, seed, mode)
    d = root / name
    if d.exists():
        shutil.rmtree(d)
    (d / "environment" / "mcp-server" / "plumberbench").mkdir(parents=True)
    (d / "solution").mkdir()
    (d / "tests" / "plumberbench").mkdir(parents=True)

    facts = mode == "facts"
    token = "" if facts else secrets.token_hex(16)
    (d / "instruction.md").write_text(instruction_text(facts))
    (d / "task.toml").write_text(TASK_TOML.format(name=name, level=level, seed=seed, mode=mode,
                                                  difficulty=DIFFICULTY[level]))

    env = d / "environment"
    (env / "Dockerfile").write_text(MAIN_DOCKERFILE)
    (env / "docker-compose.yaml").write_text(COMPOSE.format(seed=seed, level=level,
                                                            facts="1" if facts else "0", token=token))
    (env / "mcp-server" / "Dockerfile").write_text(SERVER_DOCKERFILE)
    for f in SERVER_FILES:
        shutil.copy(PKG / f, env / "mcp-server" / "plumberbench" / f)

    facts_arg = "" if facts else f'"http://mcp-server:8000/facts?token={token}"'
    (d / "solution" / "solve.sh").write_text(SOLVE_SH.format(facts_arg=facts_arg))
    shutil.copy(PKG / "solver.py", d / "solution" / "solver.py")

    tests = d / "tests"
    (tests / "Dockerfile").write_text(TESTS_DOCKERFILE)
    (tests / "test.sh").write_text(TEST_SH)
    (tests / "verify.py").write_text(VERIFY_PY.format(seed=seed, level=level))
    for f in JUDGE_FILES:
        shutil.copy(PKG / f, tests / "plumberbench" / f)
    for sh in (d / "solution" / "solve.sh", tests / "test.sh"):
        sh.chmod(0o755)
    return d


def seed_range(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Write Harbor task folders for PlumberBench.")
    ap.add_argument("--out", default="harbor/tasks")
    ap.add_argument("--levels", type=int, nargs="+", default=list(LEVELS))
    ap.add_argument("--seeds", default="0-9", help="e.g. 0-9 or 0,3,7-9")
    ap.add_argument("--mode", nargs="+", choices=("facts", "vision"), default=["facts", "vision"])
    a = ap.parse_args()
    root = Path(a.out)
    root.mkdir(parents=True, exist_ok=True)
    n = 0
    for mode in a.mode:
        for level in a.levels:
            for seed in seed_range(a.seeds):
                write_task(root, level, seed, mode)
                n += 1
    print(f"Wrote {n} tasks to {root}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
