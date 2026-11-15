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

Type `help` for the commands and what each costs, and `rules` for the full
rules, exactly as the agent gets them. When the job ends, the full result is
shown.

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
from .tasks import instruction_text
from .world import COST, DIAGNOSES, DIAGNOSIS_TEXT

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

COMMANDS = [
    # (syntax, what it does, time it takes)
    ("briefing", "hear the tenant's complaint again", f"{COST['briefing']}"),
    ("go kitchen|bathroom|utility", "walk to another room", f"{COST['go']}"),
    ("look counter|under_sink|wall", "look at another part of this room", f"{COST['look']}"),
    ("inspect TAG", "examine a part in view closely; shows a close-up until your next command",
     f"{COST['inspect']}"),
    ("run_tap cold|hot|both TICKS", "run this room's tap for 1-5 ticks", "1 per tick"),
    ("wait TICKS", "do nothing for 1-10 ticks", "1 per tick"),
    ("set_valve TAG open|half|closed", "turn a valve", f"{COST['set_valve']}"),
    ("place_bucket TAG", "set the bucket under a joint, trap or cleanout", f"{COST['place_bucket']}"),
    ("open_joint TAG", "undo a joint, remove a trap, or take out the cleanout plug", f"{COST['open_joint']}"),
    ("close_joint TAG", "refit an opened part with a new washer", f"{COST['close_joint']}"),
    ("repair TAG tighten|clear", "tighten a joint's nut, or clear an aerator or opened trap or plug",
     f"{COST['repair']}"),
    ("finish FAULT FAULT ...", "report the job finished, naming the fault types you fixed; ends the job",
     f"{COST['finish']}"),
]


def _help() -> str:
    width = max(len(c[0]) for c in COMMANDS) + 2
    lines = ["Commands, and the time units each takes:", ""]
    lines += [f"  {syntax:<{width}}{what} ({cost})" for syntax, what, cost in COMMANDS]
    lines += ["", "  score, rules, help, quit (terminal only): not actions in the house, take no time",
              "  At most 200 actions may take no time, refused ones included; then the job ends.",
              "", "Fault types:", ""]
    lines += [f"  {d:<16}{DIAGNOSIS_TEXT[d]}" for d in DIAGNOSES]
    return "\n".join(lines)


HELP = _help()


@dataclass
class Reply:
    """What a front-end shows for one command: this text and this picture, nothing else.

    `result` is the full result, filled in only once the job is over.
    """

    text: str
    image: bytes | None = None
    hotspots: list = field(default_factory=list)
    result: dict | None = None


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
    over = ep.report() if ep.state.done else None
    if line == "help":
        return Reply(HELP, result=over)
    if line == "rules":
        return Reply(instruction_text(ep.with_facts), result=over)
    if line == "score":
        if over is None:
            return Reply("Finish the job first.")
        return Reply(json.dumps(over, indent=2), result=over)
    try:
        tool, args = parse(line)
    except ValueError as e:
        return Reply(str(e), result=over)
    obs = ep.act(tool, **args)  # the text is exactly what the agent gets for this call
    return Reply(obs.text, obs.image, obs.hotspots, ep.report() if ep.state.done else None)


def start(seed: int, level: int, facts: bool, render: bool, out: Path) -> tuple[Episode, Reply]:
    ep = Episode(seed, level, facts=facts, render=render, log_dir=out / f"{seed}-{level}")
    return ep, handle(ep, "briefing")


def terminal(ep: Episode, first: Reply, out: Path) -> None:
    (out / "view.html").write_text(VIEWER)
    print(f"Open {(out / 'view.html').resolve()} in a browser to watch the view. "
          "Type `help` for the commands and `rules` for the rules.\n")

    shown_result = False

    def show(reply: Reply) -> None:
        nonlocal shown_result
        print(reply.text + "\n")
        if reply.image:
            (out / "current.jpg").write_bytes(reply.image)
        if reply.result is not None and not shown_result:
            print("The job is over. The result:\n" + json.dumps(reply.result, indent=2) + "\n")
            shown_result = True

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


def web_main() -> int:
    """`plumberbench-web`: the same as `plumberbench-play --web`."""
    import sys
    sys.argv.insert(1, "--web")
    return main()


if __name__ == "__main__":
    raise SystemExit(main())
