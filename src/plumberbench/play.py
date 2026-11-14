"""Play an episode yourself, with the same tools the agent has.

    python -m plumberbench.play --seed 3 --level 2           # in the terminal
    python -m plumberbench.play --seed 3 --level 2 --web     # in the browser
    python -m plumberbench.play --seed 3 --level 2 --facts   # also show FACTS

Terminal: the current view is written to play/current.jpg after every action.
Open play/view.html in a browser once; it shows that picture and reloads it
every second.

Browser (--web): a local page with the picture, clickable tags and buttons for
every action. It sends the same commands you would type in the terminal, through
the same function, so both show exactly the same text and pictures
(tests/test_views.py checks this against the MCP server as well).

Either way the whole episode is logged to play/<seed>-<level>/ so it can be
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
from dataclasses import dataclass, field
from pathlib import Path

from .env import Episode
from .world import DIAGNOSES

VIEWER = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>PlumberBench: current view</title>
<style>body{margin:0;background:#16181d;display:grid;place-items:center;height:100vh}
img{max-width:100vw;max-height:100vh}</style></head>
<body><img id="v" src="current.jpg" alt="current view">
<script>
setInterval(() => {
  const next = new Image();
  next.onload = () => { document.getElementById("v").src = next.src; };
  next.src = "current.jpg?" + Date.now();
}, 1000);
</script></body></html>
"""

ARGS = {
    "briefing": [], "go": ["room"], "look": ["view"], "inspect": ["tag"],
    "run_tap": ["side", "ticks"], "wait": ["ticks"], "set_valve": ["tag", "position"],
    "place_bucket": ["tag"], "open_joint": ["tag"], "close_joint": ["tag"],
    "repair": ["tag", "method"],
}

HELP = (__doc__.split("Commands are")[1].split("Playtesting")[0].strip("\n")
        + "\n\nFault names: " + ", ".join(DIAGNOSES))


@dataclass
class Reply:
    """What a front-end shows for one command: this text and this picture, nothing else."""

    text: str
    image: bytes | None = None
    hotspots: list = field(default_factory=list)


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
        try:
            args["ticks"] = int(args["ticks"])
        except ValueError:
            raise ValueError("ticks must be a whole number.") from None
    return tool, args


def handle(ep: Episode, line: str) -> Reply:
    """Run one typed command. Every front-end goes through here."""
    line = line.strip()
    if line == "help":
        return Reply(HELP)
    if line == "score":
        if not ep.state.done:
            return Reply("Finish the job first.")
        r = ep.result()
        r.pop("functional_test")
        return Reply(json.dumps(r, indent=2))
    try:
        tool, args = parse(line)
    except ValueError as e:
        return Reply(str(e))
    obs = ep.act(tool, **args)  # the text is exactly what the agent gets for this call
    return Reply(obs.text, obs.image, obs.hotspots)


def start(seed: int, level: int, facts: bool, render: bool, out: Path) -> tuple[Episode, Reply]:
    ep = Episode(seed, level, facts=facts, render=render, log_dir=out / f"{seed}-{level}")
    return ep, handle(ep, "briefing")


def terminal(ep: Episode, first: Reply, out: Path) -> None:
    (out / "view.html").write_text(VIEWER)
    print(f"Open {(out / 'view.html').resolve()} in a browser to watch the view. "
          "Type `help` for commands.\n")

    def show(reply: Reply) -> None:
        print(reply.text + "\n")
        if reply.image:
            (out / "current.jpg").write_bytes(reply.image)

    show(first)
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if line in ("quit", "exit"):
            break
        show(handle(ep, line))


def main() -> int:
    ap = argparse.ArgumentParser(description="Play PlumberBench yourself.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--facts", action="store_true", help="show the FACTS list (off for playtests)")
    ap.add_argument("--no-render", action="store_true", help="text only, no pictures")
    ap.add_argument("--web", action="store_true", help="play in the browser instead of the terminal")
    ap.add_argument("--port", type=int, default=8800, help="port for --web")
    ap.add_argument("--no-browser", action="store_true", help="with --web, do not open a browser")
    ap.add_argument("--out", default="play")
    a = ap.parse_args()

    out = Path(a.out)
    print(f"PlumberBench, house {a.seed}, level {a.level}.")
    ep, first = start(a.seed, a.level, a.facts, not a.no_render, out)
    if a.web:
        from .web import serve
        serve(ep, first, a.port, open_browser=not a.no_browser)
    else:
        terminal(ep, first, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
