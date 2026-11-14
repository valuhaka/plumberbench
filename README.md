# PlumberBench

**A house with a hidden plumbing fault, where an agent has to look, test, diagnose and repair without flooding the kitchen.**

An RL environment for AfterQuery's *Break the Agent* challenge at Junction 2026, run with Harbor and the OpenCode agent. The agent acts through MCP tools and sees each step as a rendered 3D picture with tagged parts. Faults are inside the pipes, and the tenant's complaint is often wrong, so the only way to find them is to act: run taps, watch drains, inspect joints, open things up, without making the house worse or running out of time.

## Quick start

```bash
./scripts/check.sh
./scripts/run-web.sh 3 2
uv run -m plumberbench.agent run --provider anthropic --model MODEL --levels 1 2 --seeds 0-1
./scripts/judge_runs.sh anthropic/MODEL
```

| Command | What it does | Needs |
|---|---|---|
| `check.sh` | 89 tests and the difficulty ladder (`results/ladder.md`); skips are listed with reasons | nothing; Chrome for the screen-size test |
| `run-web.sh 3 2` | play house 3 at level 2 in the browser (`uv run -m plumberbench.play` for the terminal) | nothing |
| `plumberbench.agent` | a model through the real MCP server, without Docker | an API key |
| `judge_runs.sh` | the judged runs through Harbor: smoke test, reference, baselines, agent | Docker, Harbor, an API key |

## The task

| Level | What it adds |
|---|---|
| 1 | One fault; the complaint describes the symptom |
| 2 | The complaint guesses the cause, often wrongly; one decoy stain |
| 3 | Two faults, the first hiding the second (a clog hides a leak below it, a closed valve hides a leak beyond it, a shared-branch clog looks like a trap clog) |
| 4 | Three faults, two decoys |

A careful plumber tests before opening anything, tells a supply leak (drips with the tap off) from a drain leak (drips only while water runs), takes the pressure off before undoing a joint, puts the bucket down first, and tests again after each fix. Utility-room valves are unlabelled and tags are shuffled per house.

- **The house.** A kitchen (steel sink, wooden cupboard), a bathroom (porcelain basin, white cupboard, tiles) and a utility room. Under each sink the pipe layout differs per house: the trap bends either way and sits higher or lower, and the supplies come out on either side or both on one side. A clearance check keeps every pair of parts at least 12 mm apart.
- **The world.** A pressurised supply and a gravity drain, simulated in integer ticks. Leaks drip, basins overflow, and water on the floor is damage. The picture is a pure function of the state.
- **The tools.** `briefing`, `go`, `look`, `inspect` (returns a close-up), `run_tap`, `wait`, `set_valve`, `place_bucket`, `open_joint`, `close_joint`, `repair`, `finish`. Costs are in each description. Only parts in the current view can be touched. Refused actions cost no time, but at most 200 actions may take no time.
- **What comes back.** Text in sections (`STATUS`, `RESULT`, `YOU HEAR`, `IN VIEW`), plus a JPEG whenever something in view changed; otherwise `PICTURE: unchanged since step N`. The step number is stamped on every picture so stale frames show.
- **Two modes.** `facts` also lists what the view shows as JSON (`FACTS`); `vision` gives pictures and sounds only. The scripted reference solver cannot see, so in `vision` mode it reads the facts through a token-protected route the agent has no access to.

## The reward

```
score  = repair x (0.70 + 0.15 x dryness + 0.10 x time left + 0.05 x diagnosis)
repair = faults fixed / faults present - 0.25 per thing left worse
```

The score is plain code over the simulator state. A whole-house functional test must agree with it. In Harbor the verifier runs in its own container and **replays the logged actions from the seed**, so editing result files cannot raise the reward and a missing log scores 0. Reaching the free-action limit ends the job like running out of time.

Mean over 100 houses per level (`results/ladder.md`):

| Policy | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| Reference solver | 0.96 | 0.96 | 0.95 | 0.94 |
| Do nothing, finish at once, name every fault, close the main valve, repair everything | 0 | 0 | 0 | 0 |
| Service every part, never test | 0.41 | 0.37 | 0.43 | 0.51 |

The reference solver fully repairs all 400 houses, using 36–50% of the time budget. Frontier agent results: not yet run.

## Running in Harbor

Needs a running Docker engine with `docker compose` (on a Mac: Docker Desktop, OrbStack or Colima) and `uv tool install harbor`. The task folders are generated, not committed, and `judge_runs.sh` generates them itself. By hand:

```bash
uv run -m plumberbench.tasks --out harbor/tasks --levels 1 2 3 4 --seeds 0-9 --mode facts vision
harbor lint harbor/tasks/* harbor/smoke-vision
harbor run -p harbor/smoke-vision -a oracle
harbor run -p harbor/tasks/l3-s007-facts -a oracle
harbor run -p harbor/smoke-vision -a opencode -m anthropic/MODEL --ak disable_web_search=true -k 3
```

Each task runs the simulator in a sidecar container (`mcp-server`) and connects it to the agent over MCP; the episode log comes back as an artifact. The baseline agents are `pb_agents.baselines:StopEarlyAgent` and `:CloseMainAgent` (run with `PYTHONPATH=.`).

**Run the smoke test first, with the agent and model you will be judged with.** `harbor/smoke-vision` shows a new six-digit number in a picture on each of five calls and asks for the fifth. Its verifier reports PASS, STALE (an earlier picture: OpenCode issue #51652) or BLIND (pictures are not reaching the model). Once a version passes, pin it: `OPENCODE_VERSION=x.y.z ./scripts/judge_runs.sh ...`.

## Running a model locally

`plumberbench.agent` starts one MCP server per episode and drives a model through it with the same tools, pictures and text as in Harbor. It is quicker than Harbor but its agent loop is not OpenCode's, so confirm a few tasks through Harbor.

```bash
export ANTHROPIC_API_KEY=...
uv run -m plumberbench.agent smoke --provider anthropic --model MODEL --repeat 3
uv run -m plumberbench.agent run --provider anthropic --model MODEL --levels 1 2 3 4 --seeds 0-1 --mode facts vision
uv run -m plumberbench.agent run --provider openai --model MODEL --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --key-env GEMINI_API_KEY
```

`anthropic` uses the Messages API with prompt caching. `openai` works with any OpenAI-compatible endpoint through Chat Completions; OpenAI's newer models call tools there only with reasoning off, so add `--reasoning-effort none` for them. Each run writes `runs/<provider>-<model>-<time>/`: per episode the server log, transcript, replay page and summary, plus a summary table.

## Playing it yourself

`run-web.sh` opens a local page: the picture with clickable tags, move and tap controls, the output with a command line, a status box, Help with the full rules, and the result when the job ends. The terminal version (`uv run -m plumberbench.play`) takes the same commands: `help` lists them with their costs, `rules` prints the agent's instruction. Both front-ends run commands through one handler. `tests/test_views.py` requires the MCP server, the terminal and the browser to show identical text and pictures at every step, and the browser to say nothing about the task that the agent is not told.

## The website

`site/` is a static site for Cloudflare Workers. `site/main.html` is its entry point; for now it is the demo, a step-through replay of the reference plumber on house 7, level 3. `worker/index.js` serves `site/` and maps `/` to `main.html`.

```bash
uv run -m plumberbench.demo
npx wrangler dev
npx wrangler deploy
```

`plumberbench.demo` rebuilds `site/main.html`; `wrangler dev` previews at `localhost:8787`; `wrangler deploy` publishes (run `npx wrangler login` once first).

## Repository

```
src/plumberbench/   world, sim, layout, generate (the house); scene, render (pictures); observe, env, server (MCP);
                    judge, solver, baselines; tasks (Harbor folders); play, web (people); agent (local runner);
                    replay, demo (pages)
harbor/smoke-vision/   harness check: do pictures reach the model, and stay fresh?
pb_agents/             stop-early and close-the-main baseline agents for Harbor
site/, worker/         the website and its Cloudflare Worker
tests/                 rules, judge, layouts, rendering, server, Harbor tasks, runner, front-end consistency, page layout
```

## Status

- **Verified:** all tests on Linux; on Apple silicon (Colima), the smoke test builds and passes in Harbor. Every task folder passes `harbor lint` and Harbor's task loader.
- **Not yet:** the task oracle in Harbor after the artifacts fix; images on x86; any model run; a human playtest.

Next: model runs per level and mode, to pick the judged level (reference above 0.9, agent between 0.3 and 0.6); the perception quiz; the pitch.
