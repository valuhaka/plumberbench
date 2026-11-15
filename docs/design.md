# Design

## The house

A kitchen (steel sink, wooden cupboard), a bathroom (porcelain basin, white cupboard, tiles) and a utility room with the valves, the water heater and the cleanout plug on the shared drain branch. Under each sink the pipe layout differs per house: the trap bends either way and sits higher or lower, and the supplies come out on either side or both on one side. A clearance check keeps every pair of parts at least 12 mm apart. Tags are shuffled per house and utility-room valves are unlabelled.

The world is a pressurised supply and a gravity drain, simulated in integer ticks. Leaks drip, basins overflow, and water on the floor is damage. The picture is a pure function of the state.

## Faults and levels

Six fault types: `trap_clog`, `branch_clog`, `supply_leak`, `drain_leak`, `aerator_clog`, `valve_not_open`.

| Level | Faults | What it adds |
|---|---|---|
| 1 | 1 | The complaint describes the symptom |
| 2 | 1 | The complaint guesses the cause, often wrongly; one decoy |
| 3 | 2 | The first fault hides the second: a clog hides a leak below it, a closed valve hides a leak beyond it, a shared-branch clog looks like a trap clog |
| 4 | 3 | Two decoys |

A careful plumber tests before opening anything, tells a supply leak (drips with the tap off) from a drain leak (drips only while water runs), takes the pressure off before undoing a joint, puts the bucket down first, and tests again after each fix.

## What the agent gets

- **Tools:** `briefing`, `go`, `look`, `inspect` (returns a close-up), `run_tap`, `wait`, `set_valve`, `place_bucket`, `open_joint`, `close_joint`, `repair`, `finish`. Costs are in each description. Only parts in the current view can be touched. Refused actions cost no time, but at most 200 actions may take no time; then the job ends.
- **Each response:** text in sections (`STATUS`, `RESULT`, `YOU HEAR`, `IN VIEW`) and a JPEG whenever something in view changed; otherwise `PICTURE: unchanged since step N`. The step number is stamped on every picture, so stale frames show.
- **Two modes:** `facts` also lists what the view shows as JSON (`FACTS`); `vision` gives pictures and sounds only.

## Scoring

```
score  = repair x (0.70 + 0.15 x dryness + 0.10 x time left + 0.05 x diagnosis)
repair = faults fixed / faults present - 0.25 per part left worse
```

The score is plain code over the simulator state, and a whole-house functional test must agree with it. `diagnosis` is 1 only if `finish` names exactly the fault types present.

## Why it can't be gamed

- **The verifier replays.** In Harbor it runs in its own container and replays the logged actions from the seed, so editing result files cannot raise the reward, and a missing log scores 0.
- **The agent's container holds nothing.** The simulator runs in a sidecar; the agent only reaches its MCP tools.
- **No hidden route.** The scripted reference solver cannot see, so in `vision` tasks it keeps its own copy of the house from the seed, copies every action into it and reads the facts there; it stops if its copy ever disagrees with the server.
- **Public houses are a development set.** Anyone can simulate a committed house from its seed, so grade on private ones (`plumberbench.tasks --random N`, see [harbor.md](harbor.md)).
- **The exploits score 0.** Doing nothing, finishing at once, naming every fault, closing the main valve and repairing everything all score 0 on every house; servicing every part without testing averages 0.37–0.51 (`results/ladder.md`, 100 houses per level).
- **One source of truth for people and agents.** The MCP server, the terminal and the browser show identical text and pictures at every step (`tests/test_views.py`), and the browser says nothing the agent is not told.
