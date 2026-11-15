"""The website's front page: the pitch header, with four frames from the demo run.

Built by `python -m plumberbench.demo` from the same run as the replay page, so
the frames always match it. Each frame is captioned with the command that
produced it, read from the run's log; if the run changes and a step no longer
holds the expected command, the build fails instead of mislabelling a frame.
"""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

from PIL import Image

from .icon import icon
from .render import STAMP_H

REPO = "https://github.com/valuhaka/plumberbench"
DEMO = "demo.html"

# (step, the command that step must be, caption)
FRAMES = [
    (7, "look counter", "The basin won't drain."),
    (18, "inspect C1", "Close-up of the cleanout plug."),
    (36, "open_joint T1", "Trap off, over the bucket."),
    (42, "run_tap both 1", "It drains."),
]
WIDTH = 560

CSS = r"""
:root {
  --ui: "Lucida Grande", "Lucida Sans Unicode", "Lucida Sans", Geneva, Verdana, sans-serif;
  --mono: Monaco, Menlo, "DejaVu Sans Mono", Consolas, monospace;
  --ink: #1f1f1f; --muted: #6b6b6b;
  color-scheme: light;
}
* { box-sizing: border-box; }
html { background: #e3e3e3; }
body { margin: 0; min-height: 100vh; color: var(--ink); font: 14px/1.5 var(--ui); background: linear-gradient(#f4f4f4, #e3e3e3) no-repeat; }
.wrap { padding: 0 20px; }

.site { display: flex; align-items: center; justify-content: space-between; gap: 16px; max-width: 1100px;
  margin: 18px auto 0; padding: 0 0 0 14px; height: 36px; border-radius: 6px; overflow: hidden;
  color: #222; text-shadow: 0 1px 0 rgba(255,255,255,.7);
  background: linear-gradient(#f4f4f4, #d2d2d2 50%, #c4c4c4 51%, #dadada); border: 1px solid #8a8a8a; box-shadow: 0 1px 3px rgba(0,0,0,.16); }
.brand { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; color: inherit; text-decoration: none; }
.brand svg { width: 22px; height: 22px; display: block; }
.links { display: flex; align-self: stretch; }
.links a { display: flex; align-items: center; padding: 0 20px; color: inherit; text-decoration: none; font-size: 13px;
  border-left: 1px solid #a3a3a3; box-shadow: inset 1px 0 0 rgba(255,255,255,.65); }
.links a:hover { background: rgba(0,0,0,.05); }
.site a:focus-visible { outline: 3px solid #7fb2ef; outline-offset: -3px; }

.hero { max-width: 1100px; margin: 0 auto; padding: 40px 0 56px; display: grid; justify-items: center; text-align: center; gap: 14px; }
.appicon { width: 84px; height: 84px; filter: drop-shadow(0 3px 4px rgba(0,0,0,.25)); }
.appicon svg { width: 100%; height: 100%; display: block; }
h1 { margin: 0; font: 700 clamp(28px, 4vw, 40px)/1.15 var(--ui); text-wrap: balance; }
.kicker { margin: -6px 0 0; color: var(--muted); font-size: 13px; }

.strip { list-style: none; margin: 18px 0 0; padding: 0; width: 100%; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.strip li { display: grid; gap: 8px; justify-items: center; }
.strip img { display: block; width: 100%; height: auto; background: #fff; padding: 4px; border: 1px solid #b3b3b3; box-shadow: 0 2px 5px rgba(0,0,0,.14); }
.strip code { font: 12px/1.3 var(--mono); color: #1f1f1f; background: #fff; border: 1px solid #c9c9c9; border-radius: 4px; padding: 3px 8px; }
.strip span { font-size: 12px; color: var(--muted); }

.actions { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; margin-top: 18px; }
.button { font: 13px/1 var(--ui); padding: 9px 20px; border-radius: 5px; border: 1px solid #8c8c8c; background: linear-gradient(#fdfdfd, #ececec); color: #111; text-decoration: none; }
.button.primary { background: linear-gradient(#97a0ab, #6e7783); border-color: #565e68; color: #fff; }
.button:focus-visible { outline: 3px solid #7fb2ef; outline-offset: 2px; }

@media (max-width: 760px) {
  .site { margin-top: 12px; }
  .links a { padding: 0 12px; }
  .hero { padding: 28px 0 40px; }
  .strip { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 12px; }
}
@media (max-width: 420px) {
  .brand span { display: none; }
}
"""


def command(tool: str, args: dict) -> str:
    """A logged action as the terminal command that makes it, e.g. `run_tap both 1`."""
    return " ".join([tool, *(str(v) for v in args.values())])


def frame_uri(path: Path) -> tuple[str, int]:
    """The frame without its status line, scaled to WIDTH, as a data URI; and its height."""
    im = Image.open(path).convert("RGB")
    im = im.crop((0, STAMP_H, im.width, im.height))
    height = round(WIDTH * im.height / im.width)
    im = im.resize((WIDTH, height), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), height


def build(log_dir: Path) -> str:
    log_dir = Path(log_dir)
    steps = {e["step"]: e for e in map(json.loads, (log_dir / "episode.jsonl").read_text().splitlines())}
    items = []
    for step, want, caption in FRAMES:
        e = steps.get(step)
        got = command(e["tool"], e["args"]) if e else None
        if got != want or not e.get("frame"):
            raise ValueError(f"step {step} of {log_dir} is {got!r} (frame {e and e.get('frame')}), "
                             f"not {want!r} with a frame; update lander.FRAMES")
        uri, height = frame_uri(log_dir / e["frame"])
        items.append(f'<li><img src="{uri}" alt="The picture after {html.escape(want)}: {html.escape(caption)}" '
                     f'width="{WIDTH}" height="{height}"><code>{html.escape(want)}</code>'
                     f"<span>{html.escape(caption)}</span></li>")
    strip = "\n".join(items)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PlumberBench</title>
<style>{CSS}</style></head><body>
<div class="wrap">
<nav class="site" aria-label="Site"><a class="brand" href="./">{icon("gnav")}<span>PlumberBench</span></a>
<span class="links"><a href="{DEMO}">Demo</a><a href="{REPO}">Code</a></span></nav>
<header class="hero">
  <div class="appicon">{icon("ghero")}</div>
  <h1>What&rsquo;s the next bottleneck?</h1>
  <p class="kicker">2027 &middot; After the symbols</p>
  <ol class="strip" aria-label="Four steps from the demo run">
{strip}
  </ol>
  <div class="actions"><a class="button primary" href="{DEMO}">Watch a run</a><a class="button" href="{REPO}#playing-it-yourself">Try the house</a></div>
</header>
</div>
</body></html>
"""
