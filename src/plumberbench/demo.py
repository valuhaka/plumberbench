"""Build the website: the front page and the demo replay, from one run.

    python -m plumberbench.demo

Plays the scripted reference solver on house 7, level 3, in pictures-only mode
(it reads the facts through its own channel, as in Harbor), then writes
site/demo.html, the run as a step-through replay, and site/main.html, the
front page, whose four frames come from the same run.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .env import Episode
from .observe import facts
from . import lander
from .replay import build
from .solver import Solver

NOTE = ("A house with a hidden plumbing fault. The tenant blames the kitchen trap; the real faults are "
        "elsewhere. This is the scripted reference plumber, seeing what an agent sees: one picture per step "
        "and the text below it. Step with the arrow keys or the slider.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the site's front page and demo replay.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--level", type=int, default=3)
    ap.add_argument("--log", default="results/demo/l3-s007", help="where the run's log and frames go")
    ap.add_argument("--site", default="site", help="the folder the Worker serves")
    a = ap.parse_args()

    ep = Episode(a.seed, a.level, facts=False, render=True, log_dir=a.log)
    Solver(lambda tool, args: ep.act(tool, **args).text, facts_source=lambda: facts(ep.state)).run()
    site = Path(a.site)
    site.mkdir(parents=True, exist_ok=True)
    (site / lander.DEMO).write_text(build(Path(a.log), heading="PlumberBench: the reference plumber at work", note=NOTE))
    (site / "main.html").write_text(lander.build(Path(a.log), site))
    print(f"Wrote {site / lander.DEMO} and {site / 'main.html'} (score {ep.result()['score']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
