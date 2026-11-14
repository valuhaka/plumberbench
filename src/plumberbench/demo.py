"""Build the website's demo page: the reference plumber's run as a step-through replay.

    python -m plumberbench.demo

Plays the scripted reference solver on house 7, level 3, in pictures-only mode
(it reads the facts through its own channel, as in Harbor), and writes the
replay to site/main.html, the site's entry point.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .env import Episode
from .observe import facts
from .replay import build
from .solver import Solver

NOTE = ("A house with a hidden plumbing fault. The tenant blames the kitchen trap; the real faults are "
        "elsewhere. This is the scripted reference plumber, seeing what an agent sees: one picture per step "
        "and the text below it. Step with the arrow keys or the slider.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the site's demo page.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--level", type=int, default=3)
    ap.add_argument("--log", default="results/demo/l3-s007", help="where the run's log and frames go")
    ap.add_argument("--out", default="site/main.html")
    a = ap.parse_args()

    ep = Episode(a.seed, a.level, facts=False, render=True, log_dir=a.log)
    Solver(lambda tool, args: ep.act(tool, **args).text, facts_source=lambda: facts(ep.state)).run()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(Path(a.log), heading="PlumberBench: the reference plumber at work", note=NOTE))
    print(f"Wrote {out} (score {ep.result()['score']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
