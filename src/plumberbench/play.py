"""Play an episode yourself in the terminal, with the same tools the agent has.

    python -m plumberbench.play --seed 3 --level 2
    python -m plumberbench.play --seed 3 --level 2 --facts     # also print FACTS

The current view is written to play/current.png after every action. Open
play/view.html in a browser once: it shows that picture and reloads it every
second. The whole episode is logged to play/<seed>-<level>/ so it can be
turned into a replay page.

Commands are the tool names followed by their arguments:

    briefing                go kitchen | bathroom | utility
    look counter | under_sink | wall
    inspect J3              run_tap cold|hot|both 2      wait 3
    set_valve V2 open|half|closed                        place_bucket T1
    open_joint J4           close_joint J4               repair J4 tighten|clear
    finish trap_clog supply_leak                          (fault names: see `help`)
    score                   (only after finish: shows the judge's breakdown)
    quit

Playtesting rule: do not pass --facts and do not read the source first. Every
"how was I supposed to know that?" is a fairness bug worth writing down.
"""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from .env import Episode
from .world import DIAGNOSES

VIEWER = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>PlumberBench: current view</title>
<style>body{margin:0;background:#16181d;display:grid;place-items:center;height:100vh}
img{max-width:100vw;max-height:100vh}</style></head>
<body><img id="v" src="current.png" alt="current view">
<script>
setInterval(() => {
  const next = new Image();
  next.onload = () => { document.getElementById("v").src = next.src; };
  next.src = "current.png?" + Date.now();
}, 1000);
</script></body></html>
"""

ARGS = {
    "briefing": [], "go": ["room"], "look": ["view"], "inspect": ["tag"],
    "run_tap": ["side", "ticks"], "wait": ["ticks"], "set_valve": ["tag", "position"],
    "place_bucket": ["tag"], "open_joint": ["tag"], "close_joint": ["tag"],
    "repair": ["tag", "method"],
}


def parse(line: str) -> tuple[str, dict]:
    words = shlex.split(line)
    if not words:
        raise ValueError("Type a command, or `help`.")
    tool, rest = words[0].lower(), words[1:]
    if tool == "finish":
        return tool, {"diagnosis": rest}
    if tool not in ARGS:
        raise ValueError(f"Unknown command {tool!r}. Type `help`.")
    names = ARGS[tool]
    if len(rest) != len(names):
        raise ValueError(f"{tool} takes: {' '.join(names) or 'nothing'}")
    args = dict(zip(names, rest))
    if "ticks" in args:
        args["ticks"] = int(args["ticks"])
    return tool, args


def main() -> int:
    ap = argparse.ArgumentParser(description="Play PlumberBench in the terminal.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--facts", action="store_true", help="print the FACTS list (off for playtests)")
    ap.add_argument("--no-render", action="store_true", help="text only, no images")
    ap.add_argument("--out", default="play")
    a = ap.parse_args()

    out = Path(a.out)
    ep = Episode(a.seed, a.level, facts=a.facts, render=not a.no_render,
                 log_dir=out / f"{a.seed}-{a.level}")
    print(__doc__.split("Commands are")[0].strip().splitlines()[0])
    (out / "view.html").write_text(VIEWER)
    print(f"House {a.seed}, level {a.level}. Open {(out / 'view.html').resolve()} in a browser "
          "to watch the view.\n")

    def show(obs):
        print(obs.text + "\n")
        if obs.png:
            (out / "current.png").write_bytes(obs.png)

    show(ep.act("briefing"))
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if line in ("quit", "exit"):
            break
        if line == "help":
            print(__doc__.split("Commands are")[1].split("Playtesting")[0])
            print("Fault names: " + ", ".join(DIAGNOSES) + "\n")
            continue
        if line == "score":
            if not ep.state.done:
                print("Finish the job first.\n")
                continue
            r = ep.result()
            r.pop("functional_test")
            print(json.dumps(r, indent=2) + "\n")
            continue
        try:
            tool, args = parse(line)
        except ValueError as e:
            print(f"{e}\n")
            continue
        show(ep.act(tool, **args))
        if ep.state.done:
            print(f"Score: {ep.result()['score']}. Type `score` for the breakdown, `quit` to leave.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
