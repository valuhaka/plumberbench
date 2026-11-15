# AGENTS.md

Notes for anyone, human or agent, changing this repo.

## Setup and checks

```bash
./scripts/check.sh
uv run --extra dev pytest -q tests/test_rules.py
```

`check.sh` runs every test (skips are listed with their reasons) and rewrites `results/ladder.md` and `results/ladder.json`. Python 3.11+, managed with uv; MuJoCo renders headless (EGL on Linux, CGL on macOS).

## Rules that tests enforce

- **The house is deterministic.** Seed and level fix everything; the state changes only through `sim.apply`; rendering never touches it. The verifier and the reference solver's copy of the house both rely on this.
- **The agent sees nothing hidden.** No `FACTS` in `vision` mode, no extra server routes, nothing to find in the agent's container. People get exactly what agents get: the MCP server, the terminal and the browser must show identical text and pictures (`tests/test_views.py`).
- **The committed tasks match the code.** After changing anything that goes into a task (the simulator, server, verifier, solver or `instruction.md`), run `uv run -m plumberbench.tasks` and commit `harbor/tasks/` and `registry.json`.
- **The ladder stays calibrated.** The reference solver above 0.9 on every level, every exploit at 0 (`results/ladder.md`).
- **The website shows only data.** Figures come from `results/` and renders; rebuild with `uv run -m plumberbench.demo` after changing either, and check the page by looking at it.

## Where things are

| Change | Files |
|---|---|
| Rules, faults, costs | `world.py`, `sim.py`, `generate.py`, `judge.py` |
| Pictures | `scene.py`, `layout.py`, `render.py` (all GL work on one owned thread) |
| What the agent reads | `observe.py`, `server.py`, `instruction.md` |
| Harbor tasks | `tasks.py`, `harbor/smoke-vision/`, `pb_agents/` |
| Model runs without Docker | `agent.py`, `agents_sdk.py`, `codex_cli.py`, `results.py` |
| People | `play.py`, `web.py` |
| Website | `lander.py`, `replay.py`, `demo.py`, `site/`, `worker/` |

## Style

- Plain words in everything a reader sees: docs, tool descriptions, page text. Cut any sentence a figure or the code already says.
- Shell examples have no `#` comments; they get pasted into zsh.
- Commit messages say what changed and why. Never commit keys; `runs/`, `jobs/` and `play/` are ignored.
