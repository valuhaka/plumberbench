# Fix the plumbing

You are a plumber called out to a small house. The tenant has reported a problem. Find out what is actually wrong, fix it, and leave the house in full working order, within the time budget and without flooding anything.

You work only through the tools of the `plumberbench` MCP server. Every tool call is one action in the house; there is nothing to inspect in your own container. Start with `briefing`, and call `finish` once when you are done.

## The house

**Kitchen and bathroom** each have two views:

- `counter`: the basin, with level marks numbered 1 to 8 on its back wall; a mixer tap with the hot handle (red) on the left and the cold handle (blue) on the right; and the aerator (A) on the end of the spout.
- `under_sink`: the hot supply (red) and the cold supply (blue). Each comes out of the back wall through a **wall-side joint**, then a **stop valve**, then a **tap-side joint**, then a hose up to the tap. Where the two supplies come out differs from house to house: one on each side, either way round, or both on the same side, at different heights. In the middle is the drain: the tailpiece from the basin, a slip joint, the **trap** (T, the U-bend, which may bend to either side and sit higher or lower), a second slip joint, and the arm into the wall.

**Utility room** has one view, `wall`:

- the **main valve**, low on the left, where the supply comes up from the floor past the meter;
- the **cold manifold** with three branch valves. One of them is a spare whose outlet is capped; it is normally closed;
- the **heater valve**, on the pipe that feeds the water heater. Hot water for every tap comes through it;
- the **hot manifold** with two branch valves;
- the **cleanout plug** (C), on the drain branch that both basins share, next to the big drain stack.

Branch valves are not labelled with the fixture they feed.

## How water behaves

The rules are simple and exact.

- Time moves in ticks. Most actions take time; the status line shows time used and the time budget. When the budget runs out, the job ends as it stands.
- At most 200 actions may take no time: looking around, the briefing, and refused actions all count. After the 200th, the job ends as it stands, as when time runs out. The status line shows the count.
- A supply pipe is under pressure when every valve between the main and that point is open. A half-open valve on the way gives weak flow; a closed valve gives none, and takes the pressure off everything after it.
- A leaking supply joint drips 1 unit per tick whenever it is under pressure, whether or not a tap is running. A supply joint that is undone while under pressure sprays 3 units per tick.
- A drain carries water only while there is water in its basin; a clear drain empties 2 units per tick. A leaking drain joint drips only while water passes it or stands above it.
- A clog stops water at that point; nothing below a clog gets wet. Both basins drain through the shared branch in the utility room.
- A blocked aerator makes both hot and cold weak at that tap.
- A basin holds 8 units; anything more overflows. Water that reaches the floor is damage.
- The bucket catches up to 10 units from the part it stands under.
- One fault can hide another: a closed valve hides a leak beyond it, and a clog hides a leak below it. Test again after each fix. There may be more than one fault.
- The tenant's account of the problem may be wrong.

## Reading what you see

- Every response includes a picture of the view, with every part tagged: V valve, J joint, T trap, C cleanout plug, A aerator. Tag numbers are random and say nothing about the part.
- You can only act on parts in the current view. Use `look` to change view within a room, and `go` to change room.
- `inspect` returns a close-up picture of the part instead of the whole view. The next action shows the whole view again.
- A valve's black lever points **along the pipe when open**, **across the pipe when closed**, and at 45 degrees when half open.
- After `run_tap`, the picture shows the water as it ran on the last tick: a full flow is a solid column, a weak flow only a broken trickle of drops, no flow nothing at all. Running `both` shows the two sides together, so run them one at a time to compare.
- Blue beads under a joint mean it is dripping right now. A blue pool on the floor is water; a brown patch is an old, dry stain.
- The text of each response has labelled sections: `STATUS` (step, time used/budget, damage, where you are, the bucket, washers left), `RESULT` (what the action did), `YOU HEAR` (dripping or spraying), and `IN VIEW` (the tags in the current view). A refused action returns `STATUS` and `ERROR` only.
- The step, time, damage and location are also printed at the top of the picture.
- When nothing in view has changed, no new picture is sent; the text then says `PICTURE: unchanged since step N`, and the last picture you got (stamped step N) still shows the view. Otherwise, if the step stamped in the picture differs from the one in the text, the picture is stale.

## Parts and repairs

- A leaking joint is either **loose** (tighten it) or has a **worn washer** (undo it with `open_joint`, then `close_joint` refits it with a new washer). `inspect` tells you whether a nut is loose. Forcing a nut that is already tight crushes its washer.
- Undo a supply joint only with the pressure off. The stop valve takes the pressure off the tap-side joint. The wall-side joint is upstream of the stop valve, so only a valve in the utility room takes the pressure off it.
- A clogged trap: put the bucket under it, remove it with `open_joint`, `repair` it with `clear`, then refit it with `close_joint`. A clog in the shared branch is cleared the same way at the cleanout plug.
- Washers are limited; the status line shows how many you have left.
- Actions that are impossible (a part not in the current view, a valve already in that position) are refused, cost no time and change nothing.

## Scoring

Your score is between 0 and 1. When you call `finish`, or time runs out, the house is tested: every tap must run full on hot and cold, every basin must drain, nothing may drip, every part must be refitted, and no valve may be left more closed than you found it (unless that valve was itself a fault).

    score = repair x (0.70 + 0.15 x dryness + 0.10 x time left + 0.05 x diagnosis)

- **repair**: the share of faults fixed, minus 0.25 for each thing left worse than you found it.
- **dryness**: 1 - damage / 20 (not below 0). **time left**: 1 - time used / time budget.
- **diagnosis**: 1 if the list you give to `finish` is exactly the set of fault types present.

The fault types:

- `trap_clog`: a blocked trap, the U-bend under a basin.
- `branch_clog`: a blocked drain branch, shared by both basins, behind the cleanout plug in the utility room.
- `supply_leak`: a leaking joint on a hot or cold supply line.
- `drain_leak`: a leaking joint on the drain under a basin.
- `aerator_clog`: a blocked aerator, the screen on the end of a tap's spout.
- `valve_not_open`: a valve that should be open, left closed or half open.

Fixing nothing scores 0, whatever else you do.

## Level 5

This house follows every rule above, and these as well.

- **The tenant** says only where the trouble seems to be, and may name the wrong room. Before you came, the tenant mopped the floor and bailed out the basins, so only old dry stains are left to see.
- **The number of faults** differs from house to house; the time budget and the washers do not.
- **Sounds:** `YOU HEAR` reports spraying; at this level a drip makes no sound, and shows only in the picture. Damage still rises in `STATUS` for water anywhere.
- **Weak washers:** a joint that had no pressure when you arrived (it is past a valve you found closed) may have a weak washer. It holds at first, then starts dripping after 3 to 10 ticks under pressure, counted only while it is under pressure. A joint that was under pressure when you arrived never does this. Undoing a joint tells you the state of its washer (sound, worn or weak); refitting it puts in a new one. A weak washer counts as a `supply_leak`.
- **Slow drains:** each running side of a tap, full or weak, adds 1 unit per tick to its basin. A partly blocked trap drains 1 unit per tick instead of 2, so its basin fills only with hot and cold both running. Report it as `trap_clog` and repair it like a blocked trap.
- **The main valve is seized** and will not turn. To take the pressure off a wall-side joint, close the branch valve that feeds it; you may close more than one if you do not know which, or the heater valve for a hot joint. Reopen every valve you closed.
- **`inspect` shows rather than tells** for a joint, a valve or an aerator: the close-up picture shows what you found. A loose nut is backed off, with bare thread (dark rings) between it and the fitting; a tight nut sits flush against it. A blocked aerator is crusted with white scale. Tapping the cleanout is still a sound, and an opened part is still described. A wall-side joint's close-up is taken from the side.
- **Forcing a tight nut** on a sound joint crushes its washer; on a joint that already leaks through a worn washer it changes nothing.
- **Washers:** every `close_joint` uses one, on a trap or the cleanout plug too. With none left, an opened part cannot be refitted. Removing a trap spills the 1 unit that sits in its bend.
