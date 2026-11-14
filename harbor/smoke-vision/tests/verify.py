"""Reward 1 if the answer is the number shown on the fifth call.

The printed verdict says which way it failed:
  no answer / no calls     the agent never got going (or artifacts were not collected)
  matches an earlier call  frames are going stale: the model was shown an old image
  matches no call          the model is not seeing the images at all
"""
import json
import os
from pathlib import Path

ANSWER = Path(os.environ.get("SMOKE_ANSWER", "/app/answer.txt"))
SHOWN = Path(os.environ.get("SMOKE_LOG_DIR", "/var/smoke")) / "shown.json"
OUT = Path(os.environ.get("SMOKE_VERIFIER_OUT", "/logs/verifier"))
OUT.mkdir(parents=True, exist_ok=True)

shown = json.loads(SHOWN.read_text()) if SHOWN.exists() else []
answer = "".join(ch for ch in ANSWER.read_text() if ch.isdigit()) if ANSWER.exists() else ""

if not answer or not shown:
    verdict = "no answer or no calls"
elif len(shown) != 5:
    verdict = f"called show_number {len(shown)} times, not 5"
elif answer == shown[4]:
    verdict = "PASS: images reach the model and the fifth frame was fresh"
elif answer in shown[:4]:
    verdict = f"STALE: answer matches call {shown.index(answer) + 1}, not call 5"
else:
    verdict = "BLIND: answer matches no number shown"

reward = 1 if verdict.startswith("PASS") else 0
(OUT / "reward.txt").write_text(str(reward))
(OUT / "details.json").write_text(json.dumps({"verdict": verdict, "answer": answer, "shown": shown}, indent=2))
print(verdict)
print("shown:", shown, "answer:", answer)
