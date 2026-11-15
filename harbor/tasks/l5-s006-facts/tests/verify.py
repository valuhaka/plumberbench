"""Score the episode: replay the logged actions from the seed and judge the end state.

The replay is the source of truth. The server's own result.json is only
cross-checked against it, so a damaged or missing file cannot raise the score.
Paths can be overridden (PB_LOG_DIR, PB_VERIFIER_OUT) to run this outside Harbor.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plumberbench.judge import replay, score  # noqa: E402

SEED, LEVEL = 6, 5
LOG = Path(os.environ.get("PB_LOG_DIR", "/var/plumberbench"))
OUT = Path(os.environ.get("PB_VERIFIER_OUT", "/logs/verifier"))
OUT.mkdir(parents=True, exist_ok=True)

rows = []
episode = LOG / "episode.jsonl"
if episode.exists():
    rows = [json.loads(line) for line in episode.read_text().splitlines() if line.strip()]
else:
    print("No episode log was collected from the sidecar: scoring the untouched house.")

state = replay(SEED, LEVEL, [(r["tool"], r["args"]) for r in rows])
result = score(state)
result.update(seed=SEED, level=LEVEL, steps=len(rows))

logged = LOG / "result.json"
if logged.exists():
    live = json.loads(logged.read_text()).get("score")
    result["live_score"] = live
    if live is not None and abs(live - result["score"]) > 1e-9:
        print(f"WARNING: live score {live} differs from replayed score {result['score']}")

(OUT / "details.json").write_text(json.dumps(result, indent=2))
(OUT / "reward.txt").write_text(str(result["score"]))
print(json.dumps({k: result[k] for k in ("score", "repair", "faults_fixed", "faults_total",
                                         "damage", "time_used", "time_budget", "diagnosis_correct",
                                         "left_worse")}, indent=2))
