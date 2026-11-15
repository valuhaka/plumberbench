"""Difficulty ladder: reference solver and exploit baselines on every level.

    python -m plumberbench.ladder --seeds 50 [--json results/ladder.json]

Prints one table. No rendering, so it runs in a few seconds. --json also writes
every house's score per policy and level (the website plots them).
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from .baselines import POLICIES
from .env import Episode
from .generate import LEVELS
from .solver import Solver


def run_policy(policy, seed: int, level: int) -> dict:
    ep = Episode(seed, level, facts=True, render=False)
    policy(lambda tool, args: ep.act(tool, **args).text)
    return ep.result()


def reference(call) -> None:
    Solver(call).run()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--verbose", action="store_true", help="list reference runs below 0.9")
    ap.add_argument("--json", help="also write every score here")
    args = ap.parse_args()

    policies = {"reference solver": reference, **POLICIES}
    print(f"Mean score over {args.seeds} seeds per level (minimum in brackets)\n")
    print("| Policy | " + " | ".join(f"Level {lv}" for lv in LEVELS) + " |")
    print("|---|" + "---|" * len(LEVELS))
    low = []
    every: dict[str, dict[str, list[float]]] = {}
    clean: dict[str, dict[str, int]] = {}
    for name, policy in policies.items():
        cells = []
        for level in LEVELS:
            results = [run_policy(policy, seed, level) for seed in range(args.seeds)]
            scores = [r["score"] for r in results]
            every.setdefault(name, {})[str(level)] = scores
            clean.setdefault(name, {})[str(level)] = sum(r["clean"] for r in results)
            cells.append(f"{statistics.mean(scores):.2f} ({min(scores):.2f})")
            if name == "reference solver":
                low += [r for r in results if r["score"] < 0.9]
        print(f"| {name} | " + " | ".join(cells) + " |")

    print(f"\nClean jobs (every fault fixed, nothing left worse, named right, reported done) of {args.seeds}:\n")
    print("| Policy | " + " | ".join(f"Level {lv}" for lv in LEVELS) + " |")
    print("|---|" + "---|" * len(LEVELS))
    for name in policies:
        print(f"| {name} | " + " | ".join(str(clean[name][str(lv)]) for lv in LEVELS) + " |")

    print("\nReference solver, time used as a share of the budget:")
    for level in LEVELS:
        results = [run_policy(reference, seed, level) for seed in range(args.seeds)]
        share = statistics.mean(r["time_used"] / r["time_budget"] for r in results)
        dmg = statistics.mean(r["damage"] for r in results)
        print(f"  level {level}: {share:.0%} of time, mean damage {dmg:.1f}, "
              f"full repairs {sum(r['repair'] == 1 for r in results)}/{len(results)}")
    if args.json:
        Path(args.json).write_text(json.dumps({"seeds": args.seeds, "levels": list(LEVELS), "scores": every, "clean": clean},
                                              separators=(",", ":")) + "\n")
    if args.verbose:
        for r in low:
            print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
