"""Model results for the website: one JSON file per model in results/models/.

    python -m plumberbench.results add runs/codex-gpt-6-luna-20261115-031500 --label "GPT-6 Luna (Codex)"
    python -m plumberbench.results show

`add` reads a run folder written by `python -m plumberbench.agent run` and adds its jobs
to results/models/<label>.json. Adding the same run again replaces its jobs instead of
doubling them, so a model's file can collect several runs (say levels 1 and 3-4).
Then `python -m plumberbench.demo` redraws the site with it.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

KEEP = ("level", "seed", "mode", "score", "repair", "faults", "damage", "time", "free_actions",
        "diagnosis_correct", "finished", "stop", "tool_calls", "seconds", "usage")
MODELS = Path("results/models")


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def add(run_dir: Path, label: str, note: str = "", out: Path = MODELS) -> Path:
    run_dir = Path(run_dir)
    rows = json.loads((run_dir / "summary.json").read_text())
    path = out / f"{slug(label)}.json"
    data = json.loads(path.read_text()) if path.exists() else {"label": label, "note": note, "rows": []}
    if note:
        data["note"] = note
    data["rows"] = [r for r in data["rows"] if r.get("run") != run_dir.name]
    data["rows"] += [{**{k: r[k] for k in KEEP if k in r}, "run": run_dir.name} for r in rows]
    data["rows"].sort(key=lambda r: (r["level"], r["mode"], r["seed"], r["run"]))
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


def load(out: Path = MODELS) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(Path(out).glob("*.json"))]


def stats(rows: list[dict]) -> dict:
    """Accuracy and spend for a set of jobs."""
    n = len(rows)
    use = [r.get("usage") or {} for r in rows]
    read = [u.get("input", 0) + u.get("cache_read", 0) + u.get("cache_write", 0) for u in use]
    cached = sum(u.get("cache_read", 0) for u in use)
    return {
        "jobs": n,
        "score": statistics.mean(r["score"] for r in rows) if n else None,
        "fixed_all": sum(1 for r in rows if r.get("repair", 0) == 1 or r["faults"].split("/")[0] == r["faults"].split("/")[1]),
        "diagnosis_right": sum(1 for r in rows if r["diagnosis_correct"]),
        "tokens_read": statistics.mean(read) if n else None,
        "cached_share": cached / sum(read) if sum(read) else None,
        "tokens_written": statistics.mean(u.get("output", 0) for u in use) if n else None,
        "seconds": statistics.mean(r["seconds"] for r in rows if "seconds" in r) if any("seconds" in r for r in rows) else None,
        "tool_calls": statistics.mean(r["tool_calls"] for r in rows) if n else None,
    }


def show(out: Path = MODELS) -> None:
    for m in load(out):
        print(m["label"])
        for name, keep in (("level 1-2", lambda r: r["level"] <= 2), ("level 3-4", lambda r: r["level"] >= 3)):
            rows = [r for r in m["rows"] if keep(r)]
            if not rows:
                continue
            s = stats(rows)
            print(f"  {name}: score {s['score']:.2f}, all faults fixed {s['fixed_all']}/{s['jobs']}, "
                  f"diagnosis right {s['diagnosis_right']}/{s['jobs']}; per job {s['tokens_read'] / 1000:.0f}k tokens read "
                  f"({s['cached_share']:.0%} cached), {s['tokens_written'] / 1000:.1f}k written, "
                  f"{s['tool_calls']:.0f} tool calls" + (f", {s['seconds']:.0f} s" if s["seconds"] else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect model runs for the website.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add a run folder's jobs to a model's results")
    a.add_argument("run_dir")
    a.add_argument("--label", required=True, help='how the site names the model, e.g. "GPT-6 Luna (Codex)"')
    a.add_argument("--note", default="", help="one line on how it was run")
    sub.add_parser("show", help="print accuracy and spend per model")
    args = ap.parse_args()
    if args.cmd == "add":
        print(f"Added to {add(Path(args.run_dir), args.label, args.note)}")
    show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
