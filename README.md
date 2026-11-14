# PlumberBench

**A house with a hidden plumbing fault, where an agent has to look, test, diagnose and repair without flooding the kitchen.**

The agent is a plumber in a small house: a kitchen, a bathroom and a utility room. A tenant reports a problem, and the report is often wrong. Every action is a tool call over MCP, and every response includes a rendered 3D picture of what the agent is looking at, with each part tagged. Faults are hidden inside pipes, so the agent has to work out what is wrong by running taps, watching drains, inspecting joints and opening things up, without making the house worse, wasting washers, or running out of time.

Built for AfterQuery's *Break the Agent* challenge at Junction 2026, on Harbor with the OpenCode agent.

## Quick start

```bash
./scripts/check.sh                                   # tests + difficulty ladder; no Docker, no credits
                                                     # (the screen-size test needs Chrome; skips are listed with reasons)
uv run -m plumberbench.play --seed 3 --level 2 --web # play a house yourself in the browser
uv run -m plumberbench.play --seed 3 --level 2       # ...or in the terminal (watch play/view.html)
./scripts/judge_runs.sh provider/model-name          # the judged runs, through Harbor (Docker + credits)
```

Rendering works on Linux (headless EGL, CPU is enough) and macOS (CGL).

**Playing it yourself.** The browser page keeps the job in view at all times: the tenant's complaint and the goal in a banner, with the button to report the job finished. Below it are the picture with clickable tags (each opens what that kind of part allows, with its time cost), big Move buttons that say what each move costs, tap and wait controls, the output with a command line at its foot (a click anywhere in it reaches the command line) and the history in its corner, and the status stacked in a box at the top right. Help shows the page basics, the commands and the full rules. Reporting the job opens a dialog that explains each fault type. When the job ends, both the browser and the terminal show the full result straight away; the browser shows the score large with every other fact in a table. In the terminal, `help` lists the commands with their time costs and `rules` prints the agent's instruction word for word.

Every button just types a command into the same command handler the terminal uses. `tests/test_views.py` runs one sequence of commands through the agent's MCP server, the terminal and the browser and requires the same text and the same picture, byte for byte, at every step, and the same result at the end. It also requires that the browser adds nothing: fixed payload fields, a static page, menus that depend only on a tag's letter, clickable areas only where a label is already drawn, and every sentence the page states about the task quoted from the agent's instruction, and every cost and fault description present in the terminal's `help`. The page's styling follows valuhaka/hoitoonohjaus (square boxes, flat slanted-edge buttons, window dialogs, a status box) in water blue. `tests/test_page_layout.py` loads it at seven sizes from a 360-pixel phone to 1920×1080 and checks that nothing scrolls sideways, overlaps, is cut off or opens outside the picture (skipped without Playwright and Chrome).

## What makes it hard

Difficulty comes from decisions, not from tiny pixels or trick wording:

| Level | What it adds |
|---|---|
| 1 | One fault; the complaint describes the symptom accurately |
| 2 | The complaint guesses the cause, often wrongly; one decoy stain |
| 3 | Two faults, where the first hides the second (a clog hides a leak below it; a closed valve hides a leak beyond it; a shared-branch clog looks like a trap clog) |
| 4 | Three faults, two decoys, a larger time budget |

Things a careful plumber does and a careless one does not: test before opening anything; tell a supply leak (drips with the tap off) from a drain leak (drips only while water runs); tell a clogged aerator (hot and cold both weak) from a half-closed valve (one side weak); take pressure off before undoing a joint; put the bucket down before removing a trap; test again after each fix; never force a nut that is already tight. Wiring in the utility room is unlabelled and tag numbers are shuffled per seed.

## How it works

```
src/plumberbench/
  world.py      state: parts, faults, water levels, costs. One source of truth
  sim.py        the rules: apply(state, tool, args). Deterministic, integer, no randomness
  generate.py   seeded house generator, four difficulty levels
  observe.py    the text an agent gets back, and FACTS: what the current view shows
  scene.py      the same view as shapes (no GL), built from state
  layout.py     where the pipes run under each sink; the clearance check
  render.py     MuJoCo (headless EGL) draws the scene; Pillow adds tags and the status stamp
  server.py     FastMCP server: 12 tools, image + text per response, action log
  judge.py      the score, a hidden whole-house functional test, replay
  solver.py     scripted reference plumber; talks only through the tools
  baselines.py  exploit policies the judge must give nothing
  tasks.py      writes Harbor task folders
  play.py       human play: one command handler, terminal front-end
  web.py        browser front-end over the same handler (local only, never in a task)
  replay.py     turns an episode log into a one-file HTML replay
harbor/tasks/          80 generated tasks: levels 1-4 x seeds 0-9 x {facts, vision}
harbor/smoke-vision/   harness check: do MCP images reach the model, and stay fresh?
pb_agents/             stop-early and close-the-main baseline agents for Harbor
tests/                 rules, judge, rendering, layouts, live server, generated tasks, front-end consistency, page layout
```

**The house.** The kitchen has a steel sink in a dark worktop over a wooden cupboard. The bathroom has a white porcelain basin in a white vanity with a white cupboard, a short basin mixer, a chrome trap and light grey tiles. Under each sink the pipe layout differs from house to house: the trap bends either way and sits higher or lower, and the supplies come out one on each side (either way round) or both on one side, at different heights. `layout.py` holds that geometry. The renderer draws from it, and a clearance check tests every pair of parts from different lines, every lever position and the cupboard walls, with at least 12 mm to spare. Layouts are drawn until one passes, from a random stream of their own, so a seed's faults never change. `tests/test_layout.py` checks 800 layouts, that every arrangement occurs, that the check can fail, and that the scene draws the checked points.

**The world.** Two networks. Supply is pressurized: water reaches a tap if every valve on the path from the main is open (half open gives weak flow). The drain is gravity: a basin empties at 2 units per tick unless something on the path to the stack is clogged. Time moves in ticks; leaks drip per tick; overflow and spills are damage. The image is a pure function of the state, so the picture can never disagree with the rules.

**The tools.** `briefing`, `go`, `look`, `inspect`, `run_tap`, `wait`, `set_valve`, `place_bucket`, `open_joint`, `close_joint`, `repair`, `finish`. Costs are stated in each tool's description and in the instruction. Only parts in the current view can be touched; impossible actions are refused at no cost. `inspect` returns a close-up picture of the part.

**What comes back.** Every response has a JPEG of the view and text in labelled sections:

```
STATUS: step 14 | time 23/55 | damage 2 | kitchen/under_sink | bucket under T1 (3/10) | washers 2
RESULT: You turned V2 to closed.
YOU HEAR: Dripping in this room.
IN VIEW: J1 J2 J3 J4 J9 J10 T2 V2 V11
FACTS: [...]                         (facts mode only)
```

Step, time, damage and location are also stamped into the picture, so a stale frame is detectable. All GL work runs on one dedicated thread, so the server can be called from any thread.

**Two modes.** In `facts` mode every response also ends with a FACTS list of what the view shows, under the same visibility rules as the picture. In `vision` mode the agent gets pictures and sounds only. The reference solver cannot see, so in vision mode it reads FACTS through a token-protected route; the token is only in the oracle's `solution/`, never in the agent's container.

| Runner | Sees | What it shows |
|---|---|---|
| Scripted solver | FACTS | The ceiling, reproducible through Harbor's oracle |
| Human (`play`) | Pictures only | The pictures are readable and the tasks fair |
| Agent, facts mode | Pictures + FACTS | Any gap left is decision-making |
| Agent, vision mode | Pictures only | The extra gap is perception |

## The reward

Plain code over simulator state; no model judges anything.

```
score = repair x (0.70 + 0.15 x dryness + 0.10 x time left + 0.05 x diagnosis)
repair = faults fixed / faults present - 0.25 per thing left worse
```

Everything is multiplied by `repair`, so fixing nothing scores 0 whatever else happens. "Left worse" is a joint left undone, a trap or plug left out, a valve left more closed than it started, or a sound washer crushed by overtightening. An independent functional test (every tap run, every drain watched, every joint checked for drips) must agree with the formula; the test suite checks that on 400 random end states.

In Harbor the verifier runs in its own container and **replays the logged actions from the seed**. The server's own score is only cross-checked, so tampering with result files cannot raise the reward, and a missing log scores the untouched house: 0.

## Results so far

Offline, 100 seeds per level (`results/ladder.md`):

| Policy | Level 1 | Level 2 | Level 3 | Level 4 |
|---|---|---|---|---|
| Reference solver | 0.96 (min 0.93) | 0.96 (0.93) | 0.95 (0.93) | 0.94 (0.91) |
| Do nothing | 0.00 | 0.00 | 0.00 | 0.00 |
| Finish at once | 0.00 | 0.00 | 0.00 | 0.00 |
| Name every diagnosis | 0.00 | 0.00 | 0.00 | 0.00 |
| Close the main valve | 0.00 | 0.00 | 0.00 | 0.00 |
| Repair everything in sight | 0.00 | 0.00 | 0.00 | 0.00 |
| Service every part, never test | 0.41 | 0.37 | 0.43 | 0.51 |

The reference solver fully repairs all 400 houses, using 36-50% of the time budget. "Service every part, never test" is the floor for a diligent agent that does not diagnose: it opens shut valves, tightens loose nuts and opens every trap and the cleanout, but never deals with a worn washer and spends time and washers on parts that were fine.

Frontier agent runs: not yet done (needs the event's harness and credits).

## Running in Harbor

```bash
python -m plumberbench.tasks --out harbor/tasks --levels 1 2 3 4 --seeds 0-9 --mode facts vision
harbor run -p harbor/tasks/l3-s007-facts -a oracle                    # reference run
harbor run -p harbor/tasks/l3-s007-facts -a nop                       # do nothing
PYTHONPATH=. harbor run -p harbor/tasks/l3-s007-facts -a pb_agents.baselines:StopEarlyAgent
harbor run -p harbor/tasks/l3-s007-facts -a opencode -m provider/model-name -k 3
python -m plumberbench.replay <trial artifacts>/var/plumberbench -o replay.html
```

Each task runs the simulator as a compose sidecar (`mcp-server`, Python 3.13 slim + Mesa EGL), connected to the agent over streamable HTTP MCP. The episode log and frames are collected as artifacts from the sidecar.

**Run the smoke test first, with the exact agent and model you will be judged with.** `harbor/smoke-vision` shows a new six-digit number as a picture on each of five calls and asks for the fifth. Its verifier tells the three outcomes apart: PASS, STALE (the answer matches an earlier call: OpenCode issue #51652) or BLIND (images are not reaching the model: wrong OpenCode version, or a gateway that does not declare image input).

## Not yet verified

- **No container has been built.** Docker Hub was blocked where this was written. The simulator, server, solver and verifier are tested natively (Python 3.13, Mesa EGL on Ubuntu 24.04); the `python:3.13-slim` image with the listed Mesa packages is untested.
- **No Harbor run has happened.** Task folders follow Harbor's own examples (commit b06002e, 2026-11-13): `hello-mcp` for the MCP sidecar, `sidecar-artifacts` for sidecar artifacts and the separate verifier. Directory artifacts and `-k` are from Harbor's source, not from a run.
- **No model has played it.** Whether a frontier agent shows a gap is the open question; the ladder exists so the level can be picked once real numbers are in.
- **No human playtest yet.** Two or three people should play three to five houses each with `play --web` (no `--facts`), without reading the source.

## Next

1. Perception quiz: single frames with questions answered from FACTS (is V3 open, half or closed? which joints drip? what is the basin level?), to measure how much of the images-only gap is perception and check the task is not saturated.
2. Hour one at the event: build the images, run the smoke test three times, run the oracle on one task.
3. Agent runs on levels 1-4 in both modes; pick the judged level where the reference is above 0.9 and the agent lands between 0.3 and 0.6.
4. Stretch (tiebreaker, and Modal's challenge): fine-tune a small open-weight vision model on reference-solver trajectories and show the before and after on held-out seeds.
