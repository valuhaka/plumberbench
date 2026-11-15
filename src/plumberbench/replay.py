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
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ --ui: "Lucida Grande", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
          --mono: Menlo, Monaco, "DejaVu Sans Mono", Consolas, monospace; --ink: #1f2328; --muted: #5f6670; --line: #d9dbde; }}
  * {{ box-sizing: border-box; }}
  body {{ font: 15px/1.5 var(--ui); margin: 0; background: #f3f3f2; color: var(--ink); }}
  .wrap {{ max-width: 1240px; margin: 0 auto; padding: 14px 20px 24px; display: grid; gap: 12px; }}
  nav {{ display: flex; align-items: center; justify-content: space-between; height: 40px; padding: 0 0 0 14px; background: #fff;
         border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
  nav b {{ font-size: 15px; }}
  nav span {{ display: flex; align-self: stretch; }}
  nav a {{ display: flex; align-items: center; padding: 0 16px; color: var(--ink); text-decoration: none; font-size: 13.5px; }}
  nav a:hover {{ background: #f2f4f7; }}
  .card {{ background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }}
  header h1 {{ font-size: 18px; margin: 0 0 2px; }}
  header p {{ margin: 0; color: var(--muted); }}
  header p.note {{ margin-top: 4px; max-width: 80ch; }}
  main {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 380px); gap: 12px; align-items: start; }}
  .view {{ width: 100%; max-width: min(800px, max(420px, calc((100dvh - 300px) * 4 / 3))); justify-self: center; }}
  img {{ width: 100%; border-radius: 6px; display: block; background: #0b0d10; box-shadow: 0 0 0 1px var(--line); }}
  pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; font: 12.5px/1.55 var(--mono); }}
  .call {{ color: #1d4f91; font-weight: 700; margin-bottom: 6px; font-family: var(--mono); font-size: 13px; }}
  .controls {{ display: flex; gap: 8px; align-items: center; margin-top: 10px; }}
  input[type=range] {{ flex: 1; min-width: 0; accent-color: #2a6fcb; }}
  button {{ font: 14px/1 var(--ui); background: #fff; color: var(--ink); border: 1px solid #c9cbcf; border-radius: 7px; padding: 7px 14px; cursor: pointer; }}
  button:hover {{ background: #f4f5f7; }}
  #pos {{ color: var(--muted); font-size: 13px; min-width: 4.5em; text-align: right; font-variant-numeric: tabular-nums; }}
  details {{ margin-top: 10px; color: var(--muted); font-size: 13px; }}
  details summary {{ cursor: pointer; color: #2a6fcb; }}
  details pre {{ margin-top: 6px; background: #f6f6f6; border: 1px solid var(--line); border-radius: 6px; padding: 8px; color: var(--ink); }}
  .ok {{ color: #18794e; font-weight: 700; }} .bad {{ color: #b42318; font-weight: 700; }}
  @media (max-width: 820px) {{ main {{ grid-template-columns: minmax(0, 1fr); }} .view {{ max-width: 800px; }}
    nav a {{ padding: 0 11px; }} }}
</style></head><body><div class="wrap">
{nav}<header class="card"><h1>{heading}</h1><p class="score">{summary}</p>{note}</header>
<main>
  <div class="view"><img id="frame" alt="view at this step">
    <div class="controls"><button id="prev" aria-label="Previous step">&larr;</button>
      <input id="slider" type="range" min="0" max="{last}" value="0" aria-label="Step">
      <button id="next" aria-label="Next step">&rarr;</button><span id="pos"></span></div></div>
  <div class="card"><div class="call" id="call"></div><pre id="text"></pre>
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
</script></div></body></html>
"""


NAV = ('<nav aria-label="Site"><b>PlumberBench</b><span><a href="play/">Play</a><a href="./">Pitch</a>'
       '<a href="./#results">Results</a></span></nav>\n')


def build(log_dir: Path, heading: str | None = None, note: str | None = None, site: bool = False) -> str:
    """The replay page; `site` adds the website's navigation bar (for site/demo.html)."""
    rows = [json.loads(line) for line in (log_dir / "episode.jsonl").read_text().splitlines() if line.strip()]
    result = json.loads((log_dir / "result.json").read_text())
    steps = []
    img = None  # a step without a new picture still shows the last one
    for r in rows:
        if r.get("frame") and (log_dir / r["frame"]).exists():
            mime = "image/png" if r["frame"].endswith(".png") else "image/jpeg"
            img = f"data:{mime};base64," + base64.b64encode((log_dir / r["frame"]).read_bytes()).decode()
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
    note_html = f'<p class="note">{html.escape(note)}</p>' if note else ""
    return PAGE.format(title=f"house {result['seed']} level {result['level']}", nav=NAV if site else "",
                       heading=html.escape(heading or f"House {result['seed']}, level {result['level']}"),
                       note=note_html, summary=summary, last=max(len(steps) - 1, 0),
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
