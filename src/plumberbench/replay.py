"""Turn an episode log into one self-contained HTML page for the demo.

    python -m plumberbench.replay /var/plumberbench -o replay.html

Works on any log directory written by `Episode` (the MCP server, `play`, or
Harbor's collected artifacts). Use the arrow keys or the slider to step.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>PlumberBench replay: {title}</title>
<style>
  body {{ font: 15px/1.45 system-ui, sans-serif; margin: 0; background: #16181d; color: #e8e8e8; }}
  header {{ padding: 14px 22px; background: #0e0f12; border-bottom: 1px solid #2a2d35; }}
  header h1 {{ font-size: 18px; margin: 0 0 4px; }}
  header p {{ margin: 0; color: #a9adb6; }}
  main {{ display: grid; grid-template-columns: minmax(0, 800px) minmax(280px, 1fr); gap: 20px; padding: 18px 22px; }}
  img {{ width: 100%; border-radius: 6px; display: block; background: #000; }}
  pre {{ white-space: pre-wrap; word-break: break-word; background: #0e0f12; padding: 12px; border-radius: 6px;
         margin: 0 0 12px; font: 13px/1.5 ui-monospace, monospace; }}
  .call {{ color: #ffd166; font-weight: 600; margin-bottom: 6px; font-family: ui-monospace, monospace; }}
  .controls {{ display: flex; gap: 10px; align-items: center; margin-top: 10px; }}
  input[type=range] {{ flex: 1; }}
  button {{ background: #2a2d35; color: #e8e8e8; border: 0; border-radius: 5px; padding: 6px 12px; cursor: pointer; }}
  .score {{ font-size: 15px; }}
  .ok {{ color: #7bd88f; }} .bad {{ color: #ff6b6b; }}
</style></head><body>
<header><h1>House {seed}, level {level}</h1><p class="score">{summary}</p></header>
<main>
  <div><img id="frame" alt="view at this step">
    <div class="controls"><button id="prev">&larr;</button>
      <input id="slider" type="range" min="0" max="{last}" value="0">
      <button id="next">&rarr;</button><span id="pos"></span></div></div>
  <div><div class="call" id="call"></div><pre id="text"></pre>
    <details><summary>Faults (ground truth)</summary><pre>{faults}</pre></details></div>
</main>
<script>
const steps = {steps};
let i = 0;
const $ = id => document.getElementById(id);
function show(k) {{
  i = Math.max(0, Math.min(steps.length - 1, k));
  const s = steps[i];
  if (s.img) $("frame").src = s.img;
  $("call").textContent = s.call;
  $("text").textContent = s.text;
  $("slider").value = i;
  $("pos").textContent = (i + 1) + " / " + steps.length;
}}
$("prev").onclick = () => show(i - 1);
$("next").onclick = () => show(i + 1);
$("slider").oninput = e => show(+e.target.value);
document.addEventListener("keydown", e => {{
  if (e.key === "ArrowLeft") show(i - 1);
  if (e.key === "ArrowRight") show(i + 1);
}});
show(0);
</script></body></html>
"""


def build(log_dir: Path) -> str:
    rows = [json.loads(line) for line in (log_dir / "episode.jsonl").read_text().splitlines() if line.strip()]
    result = json.loads((log_dir / "result.json").read_text())
    steps = []
    for r in rows:
        img = None
        if r.get("frame") and (log_dir / r["frame"]).exists():
            img = "data:image/png;base64," + base64.b64encode((log_dir / r["frame"]).read_bytes()).decode()
        args = ", ".join(f"{k}={json.dumps(v)}" for k, v in r["args"].items())
        steps.append({"img": img, "call": f"{r['tool']}({args})", "text": r["text"]})
    checks = result.get("functional_test", {})
    failed = [k for k, ok in checks.items() if not ok]
    test = ('<span class="ok">house test passed</span>' if not failed else
            '<span class="bad">house test failed: ' + html.escape(", ".join(failed)) + "</span>")
    summary = (f"score <b>{result['score']}</b> &middot; faults fixed {result['faults_fixed']}/"
               f"{result['faults_total']} &middot; damage {result['damage']} &middot; time "
               f"{result['time_used']}/{result['time_budget']} &middot; diagnosis "
               f"{'right' if result['diagnosis_correct'] else 'wrong'} &middot; {test}")
    return PAGE.format(title=f"house {result['seed']} level {result['level']}", seed=result["seed"],
                       level=result["level"], summary=summary, last=max(len(steps) - 1, 0),
                       faults=html.escape(json.dumps(result.get("faults", []), indent=1)),
                       steps=json.dumps(steps).replace("</", "<\\/"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a replay page from an episode log.")
    ap.add_argument("log_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("replay.html"))
    a = ap.parse_args()
    a.out.write_text(build(a.log_dir))
    print(f"Wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
