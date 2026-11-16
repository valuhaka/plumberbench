"""The website's front page: the pitch, told in figures.

Built by `python -m plumberbench.demo`, from data in the repo only:
    run frames      the demo run, each captioned with the command that made it, checked
                    against the run's log (the build fails rather than mislabel a frame)
    pictures        rendered here from the simulator: a blocked trap that looks fine, one
                    test's before and after, a leak's puddle, and each fault's part up close
    models chart    every results/models/*.json (python -m plumberbench.results add ...),
                    on the houses every model played
    validity tiles  results/ladder.json (python -m plumberbench.ladder --json)
    reward bar      the judge's weights

The motivating numbers are cited in FACTS. Pictures go to site/img/. When presenting, the
arrow keys step from section to section.
"""
from __future__ import annotations

import html
import io
import json
import statistics
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from .generate import LEVELS, generate
from .icon import icon
from .judge import REGRESSION_PENALTY, W_DRY, W_NAMED, W_QUICK, W_REPAIR
from .play import COMMANDS
from .results import stats

REPO = "https://github.com/valuhaka/plumberbench"
SITE = "https://plumberbench.org"
DESCRIPTION = ("AI can solve olympiad maths but can't fix a leaky pipe. In PlumberBench an agent gets a house "
               "with hidden plumbing faults, seen only in pictures, and has to look, test, diagnose and repair.")
DEMO = "demo.html"
PLAY = "play/"  # the online play server (online.py), behind worker/online/
OFFLINE = "play-offline.html"  # what /play shows while that is not deployed
LOCAL_PLAY = "uvx --from git+https://github.com/valuhaka/plumberbench plumberbench-web"
ESC = html.escape

# (step, the command that step must be, caption)
FRAMES = [
    (7, "look counter", "The basin won't drain."),
    (18, "inspect C1", "Close-up of the cleanout plug."),
    (36, "open_joint T1", "Trap off, over the bucket."),
    (42, "run_tap both 1", "It drains."),
]
WIDTH = 560

# One house per fault type (seed 7, level 1), to draw that fault's part up close.
FAULTS = [
    ("trap_clog", {"type": "trap_clog", "id": "trap.kitchen"}),
    ("branch_clog", {"type": "branch_clog", "id": "cleanout"}),
    ("supply_leak", {"type": "supply_leak", "id": "jin.kitchen.cold", "cause": "loose"}),
    ("drain_leak", {"type": "drain_leak", "id": "jtail.kitchen", "cause": "loose"}),
    ("aerator_clog", {"type": "aerator_clog", "id": "aer.kitchen"}),
    ("valve_not_open", {"type": "valve_not_open", "id": "stop.kitchen.cold", "pos": "half"}),
]
# World model: a blocked kitchen trap, before and after running the tap.
PREDICT = ({"type": "trap_clog", "id": "trap.kitchen"}, "run_tap", {"side": "cold", "ticks": 3})

# Baselines are drawn in neutral ink; the models take the validated categorical slots in order.
SERIES = [
    ("reference solver", "Reference plumber", "#3d434b"),
    ("service all, never test", "Services everything, never tests", "#9a9a9a"),
]
MODEL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

# The world the benchmark is for, with sources: (number, what it counts, source, url).
IMO = ("35/42", "AI's gold-medal score at the 2025 International Mathematical Olympiad",
       "The New York Times, via The Star",
       "https://www.thestar.com.my/tech/tech-news/2025/07/24/google-ai-system-wins-gold-medal-in-international-mathematical-olympiad")
FACTS = [
    ("1 trillion", "gallons of water lost to household leaks in the US every year", "US EPA",
     "https://www.epa.gov/node/288682"),
    ("550,000", "plumbers short in the US, forecast for 2026", "PM Magazine, on a LIXIL study",
     "https://www.pmmag.com/articles/107673-plumbing-industry-adds-442b-to-us-economy-faces-550-000-worker-shortage"),
    ("1.7 million", "skilled-trade job openings in the US every year through 2035",
     "Fortune, on JFF and the Burning Glass Institute",
     "https://fortune.com/2026/10/09/leaky-pipeline-1-7-million-trade-jobs-open-annually-2035/"),
]
REWARD = [("Base", W_REPAIR, "#2a78d6", "#ffffff"), ("Dry floor", W_DRY, "#eb6834", "#ffffff"),
          ("Time left", W_QUICK, "#1baf7a", "#ffffff"), ("Right diagnosis", W_NAMED, "#eda100", "#0b0b0b")]


# ------------------------------------------------------------------ pictures

def command(tool: str, args: dict) -> str:
    """A logged action as the terminal command that makes it, e.g. `run_tap both 1`."""
    return " ".join([tool, *(str(v) for v in args.values())])


def _save(jpeg: bytes, path: Path, width: int) -> tuple[int, int]:
    """Write a picture without its status line, scaled to `width`; return its size."""
    from .render import STAMP_H
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    im = im.crop((0, STAMP_H, im.width, im.height))
    height = round(width * im.height / im.width)
    im.resize((width, height), Image.LANCZOS).save(path, "JPEG", quality=82, optimize=True, progressive=True)
    return width, height


def _render(s, focus=None) -> bytes:
    from .render import render  # late, so importing this module needs no GL
    return render(s, focus)[0]


def hero_frames(log_dir: Path, img: Path) -> list[dict]:
    steps = {e["step"]: e for e in map(json.loads, (log_dir / "episode.jsonl").read_text().splitlines())}
    out = []
    for step, want, caption in FRAMES:
        e = steps.get(step)
        got = command(e["tool"], e["args"]) if e else None
        if got != want or not e.get("frame"):
            raise ValueError(f"step {step} of {log_dir} is {got!r} (frame {e and e.get('frame')}), "
                             f"not {want!r} with a frame; update lander.FRAMES")
        name = f"run-{step:03d}.jpg"
        w, h = _save((log_dir / e["frame"]).read_bytes(), img / name, WIDTH)
        out.append({"src": f"img/{name}", "w": w, "h": h, "cmd": want, "caption": caption})
    return out


def rendered_pictures(img: Path) -> dict:
    faults = []
    for kind, fault in FAULTS:
        s = generate(7, 1, faults=[fault])
        part = s.comps[fault["id"]]
        s.room, s.view = part.room, part.view
        name = f"fault-{kind}.jpg"
        w, h = _save(_render(s, part.tag), img / name, 400)
        faults.append({"src": f"img/{name}", "w": w, "h": h, "kind": kind, "tag": part.tag})
    from . import sim
    fault, tool, args = PREDICT
    s = generate(7, 1, faults=[fault])
    s.room, s.view = "kitchen", "under_sink"
    hidden = _save(_render(s), img / "hidden.jpg", 400)
    s.room, s.view = "kitchen", "counter"
    before = _save(_render(s), img / "predict-before.jpg", 400)
    sim.apply(s, tool, args)
    after = _save(_render(s), img / "predict-after.jpg", 400)
    s = generate(7, 1, faults=[{"type": "drain_leak", "id": "jtail.kitchen", "cause": "loose"}])
    s.room, s.view = "kitchen", "under_sink"
    for _ in range(2):
        sim.apply(s, "run_tap", {"side": "both", "ticks": 5})
    puddle = _save(_render(s), img / "puddle.jpg", 400)
    return {"faults": faults, "hidden": ("img/hidden.jpg", *hidden),
            "puddle": ("img/puddle.jpg", *puddle), "damage": s.damage,
            "predict": {"cmd": command(tool, args), "before": ("img/predict-before.jpg", *before),
                        "after": ("img/predict-after.jpg", *after)}}


# ------------------------------------------------------------------ data

def load_results(results: Path) -> tuple[dict, list[dict]]:
    ladder = json.loads((results / "ladder.json").read_text())
    models = [json.loads(p.read_text()) for p in sorted((results / "models").glob("*.json"))]
    return ladder, models


# ------------------------------------------------------------------ figures

def legend(entries: list[tuple[str, str, str]]) -> str:
    """entries: (name, colour, key class)."""
    items = "".join(f'<li><span class="key {cls}" style="background:{c}"></span>{ESC(n)}</li>' for n, c, cls in entries)
    return f'<ul class="legend">{items}</ul>'


def pictures_jobs(models: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Each model with its pictures-only jobs: what the chart and table compare."""
    return [(m, [r for r in m["rows"] if r["mode"] == "pictures only"]) for m in models]


def is_clean(r: dict) -> bool:
    return r.get("repair") == 1 and r["diagnosis_correct"] and bool(r.get("finished"))


def models_chart(ladder: dict, models: list[dict]) -> str:
    """Every pictures-only job as a dot, by level and model: filled if it was a clean job
    (every fault fixed, named right, reported done), hollow if not; a short line marks a
    model's mean. The reference plumber (solid) and the never-test policy (dashed) are each
    level's means over every house, in neutral ink, for scale."""
    jobs = pictures_jobs(models)
    levels = sorted({r["level"] for _, rows in jobs for r in rows})
    if not levels:
        return ""
    left, right, top, plot_h, width = 48, 12, 12, 250, 960
    band = (width - left - right) / len(levels)
    slot = band / (len(models) + 1)
    y = lambda v: top + (1 - v) * plot_h
    parts = []
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line x1="{left - 8}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{left - 14}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v:g}</text>')
    for i, lv in enumerate(levels):
        x0 = left + i * band
        if i:
            parts.append(f'<line x1="{x0:.1f}" x2="{x0:.1f}" y1="{top}" y2="{top + plot_h}" class="sep"/>')
        parts.append(f'<text x="{x0 + band / 2:.1f}" y="{top + plot_h + 22}" class="lv" text-anchor="middle">Level {lv}</text>')
        for key, name, color in SERIES:
            scores = ladder["scores"].get(key, {}).get(str(lv))
            if not scores:
                continue
            mean = statistics.mean(scores)
            parts.append(f'<line x1="{x0 + 6:.1f}" x2="{x0 + band - 6:.1f}" y1="{y(mean):.1f}" y2="{y(mean):.1f}" '
                         f'class="base{" dash" if "never" in key else ""}" stroke="{color}"/>')
            tip = f"{mean:.2f} mean\n{name}, level {lv}\n{len(scores)} houses"
            parts.append(f'<rect x="{x0 + 6:.1f}" y="{y(mean) - 5:.1f}" width="{band - 12:.1f}" height="10" class="hit" '
                         f'tabindex="0" data-tip="{ESC(tip)}" aria-label="{ESC(tip.replace(chr(10), ", "))}"/>')
        for k, ((m, rows), color) in enumerate(zip(jobs, MODEL_COLORS)):
            mine = [r for r in rows if r["level"] == lv]
            cx = x0 + slot * (k + 1)
            if len(mine) > 1:
                mean = statistics.mean(r["score"] for r in mine)
                parts.append(f'<line x1="{cx - slot * 0.38:.1f}" x2="{cx + slot * 0.38:.1f}" y1="{y(mean):.1f}" '
                             f'y2="{y(mean):.1f}" class="mean" stroke="{color}"/>')
            for j, r in enumerate(sorted(mine, key=lambda r: r["score"])):
                dx = (j - (len(mine) - 1) / 2) * 7
                fill = color if is_clean(r) else "#ffffff"
                parts.append(f'<circle cx="{cx + dx:.1f}" cy="{y(r["score"]):.1f}" r="5" fill="{fill}" stroke="{color}" stroke-width="2"/>')
                left_in = r.get("finished") and r.get("repair", 1) < 1
                tip = (f"{r['score']:.2f}\n{m['label']}, level {lv}, house {r['seed']}\n"
                       + ("clean job" if is_clean(r) else f"faults fixed {r['faults']}"
                          + (", reported done with a fault left" if left_in else "")
                          + ("" if r["diagnosis_correct"] else ", diagnosis wrong")))
                parts.append(f'<rect x="{cx + dx - 9:.1f}" y="{y(r["score"]) - 9:.1f}" width="18" height="18" class="hit" '
                             f'tabindex="0" data-tip="{ESC(tip)}" aria-label="{ESC(tip.replace(chr(10), ", "))}"/>')
    height = top + plot_h + 32
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Every pictures-only job by level and model, filled when it was a clean job; '
            f'the table below lists the same">' + "".join(parts) + "</svg>")


def model_table(models: list[dict]) -> str:
    """Per model, pictures-only jobs: mean score and clean jobs per level, then what it took."""
    jobs = pictures_jobs(models)
    levels = sorted({r["level"] for _, rows in jobs for r in rows})
    head = "".join(f"<th>Level {lv}</th>" for lv in levels)
    rows = []
    for m, mine in jobs:
        if not mine:
            continue
        cells = []
        for lv in levels:
            at = [r for r in mine if r["level"] == lv]
            cells.append(f"<td>{statistics.mean(r['score'] for r in at):.2f} "
                         f"<span>{sum(map(is_clean, at))}/{len(at)} clean</span></td>" if at else "<td>–</td>")
        st = stats(mine)
        left = sum(1 for r in mine if r.get("finished") and r.get("repair", 1) < 1)
        secs = f"{st['seconds']:.0f} s" if st["seconds"] else "–"
        rows.append(f'<tr><th>{ESC(m["label"])}</th><td class="dim">{ESC(m.get("harness", ""))}</td>{"".join(cells)}'
                    f"<td>{left} of {len(mine)}</td><td>{st['tool_calls']:.0f}</td><td>{secs}</td></tr>")
    return ('<div class="models"><table><thead><tr><th>Model</th><th>Run with</th>' + head +
            '<th>Done with a fault left</th><th>Actions</th><th>Time</th></tr></thead>'
            '<tbody>' + "".join(rows) + "</tbody></table></div>")


def finding(ladder: dict, models: list[dict]) -> str:
    """The headline, from the data: at the top level, how many model jobs were reported done
    with a fault still in the house, against the reference plumber's clean jobs."""
    jobs = [r for _, rows in pictures_jobs(models) for r in rows]
    if not jobs:
        return ""
    top = max(r["level"] for r in jobs)
    at = [r for r in jobs if r["level"] == top]
    left = sum(1 for r in at if r.get("finished") and r.get("repair", 1) < 1)
    clean = sum(map(is_clean, at))
    ref = ladder.get("clean", {}).get("reference solver", {}).get(str(top))
    tiles = [(f"{left} of {len(at)}", f"level {top} jobs by models reported done with a fault still in the house"),
             (f"{clean} of {len(at)}", f"level {top} jobs by models that were clean")]
    if ref is not None:
        tiles.append((f"{ref} of {ladder['seeds']}", f"level {top} houses the reference plumber left clean"))
    items = "".join(f"<li><b>{v}</b><span>{ESC(t)}</span></li>" for v, t in tiles)
    return f'<ul class="tiles">{items}</ul>'


def validity(ladder: dict) -> str:
    """Three numbers that say the score means something: the reference plumber near 1, the
    policy that never tests far below, and every exploit at 0."""
    every = lambda key: [x for lv in ladder["levels"] for x in ladder["scores"][key][str(lv)]]
    exploits = [k for k in ladder["scores"] if k not in ("reference solver", "service all, never test")]
    houses = ladder["seeds"] * len(ladder["levels"])
    tiles = [(f"{statistics.mean(every('reference solver')):.2f}", "reference plumber"),
             (f"{statistics.mean(every('service all, never test')):.2f}", "service everything, never test"),
             (f"{max(max(every(k)) for k in exploits):.2f}", f"best of {len(exploits)} exploits")]
    items = "".join(f"<li><b>{v}</b><span>{ESC(t)}</span></li>" for v, t in tiles)
    return f'<ul class="tiles" aria-label="Mean score over {houses} houses">{items}</ul>'


def reward_bar() -> str:
    total = sum(w for _, w, _, _ in REWARD)
    parts = "".join(f'<span class="part" style="flex:{w / total:.4f};background:{c};color:{ink}">{w:.2f}</span>'
                    for n, w, c, ink in REWARD)
    keys = "".join(f'<li><span class="key" style="background:{c}"></span>{ESC(n)}</li>' for n, _, c, _ in REWARD)
    return (f'<div class="reward"><code class="times">repair ×</code><div class="bar" role="img" '
            f'aria-label="Score is repair times: base {W_REPAIR}, dry floor {W_DRY}, time left {W_QUICK}, '
            f'right diagnosis {W_NAMED}">{parts}</div></div>'
            f'<ul class="legend">{keys}</ul>'
            f'<p class="fine">repair: share of faults fixed, &minus;{REGRESSION_PENALTY:g} per part left worse</p>')


# ------------------------------------------------------------------ page

def models_slide(ladder: dict, models: list[dict]) -> str:
    if not models:
        return ""
    entries = [(m["label"], c, "") for m, c in zip(models, MODEL_COLORS)]
    entries += [(n, c, "line" + (" dash" if "never" in k else "")) for k, n, c in SERIES]
    entries += [("Clean job", "#3d434b", ""), ("Fault left or misnamed", "#ffffff", "ring")]
    return f"""
<section class="slide" id="results">
<h2>Who fixes the house</h2>
{finding(ladder, models)}
{legend(entries)}
<div class="chart-wrap">{models_chart(ladder, models)}</div>
{model_table(models)}
</section>
"""


def _img(src, w, h, alt):
    return f'<img src="{src}" width="{w}" height="{h}" alt="{ESC(alt)}" loading="lazy">'


def build(log_dir: Path, site: Path, results: Path = Path("results")) -> str:
    """Write the pictures to site/img/ and return main.html."""
    log_dir, site, results = Path(log_dir), Path(site), Path(results)
    img = site / "img"
    img.mkdir(parents=True, exist_ok=True)
    frames = hero_frames(log_dir, img)
    pics = rendered_pictures(img)
    ladder, models = load_results(results)
    tools = [c[0].split()[0] for c in COMMANDS]

    strip = "\n".join(
        f'<li>{_img(f["src"], f["w"], f["h"], "The picture after " + f["cmd"] + ": " + f["caption"])}'
        f'<code>{ESC(f["cmd"])}</code></li>' for f in frames)
    p = pics["predict"]
    leak = pics["faults"][[f["kind"] for f in pics["faults"]].index("supply_leak")]
    facts = "".join(f'<li><b>{ESC(n)}</b><span>{ESC(what)}</span></li>' for n, what, _, _ in FACTS)
    sources = " &middot; ".join(f'<a href="{url}">{ESC(src)}</a>' for _, _, src, url in [IMO] + FACTS)
    faults = "".join(
        f'<figure>{_img(f["src"], f["w"], f["h"], f["kind"].replace("_", " ") + ", " + f["tag"] + " up close")}'
        f'<figcaption><code>{f["kind"]}</code></figcaption></figure>' for f in pics["faults"])

    body = f"""
<section class="slide hero-slide" id="top">
<nav class="site" aria-label="Site"><a class="brand" href="./">{icon("gnav")}<span>PlumberBench</span></a>
<span class="links"><a href="{PLAY}">Play</a><a href="{DEMO}">Demo</a><a href="#results">Results</a><a href="{REPO}">Code</a></span></nav>
<header class="hero">
  <p class="eyebrow"><span class="live-dot"></span> A benchmark for agents that act in the real world</p>
  <h1>AI can solve any maths problem.<br><span>It can&rsquo;t fix your leaky pipes. Yet.</span></h1>
  <div class="versus">
    <a class="card proof" href="{IMO[3]}"><b>{IMO[0]}</b><span>{ESC(IMO[1])}</span></a>
    <figure class="card">{_img(leak["src"], leak["w"], leak["h"], "A supply joint dripping under a basin")}</figure>
  </div>
  <div class="actions"><a class="button primary" href="{PLAY}">Try the bench <span aria-hidden="true">&rarr;</span></a><a class="button" href="{DEMO}">Watch the run</a></div>
  <p class="fine hero-note">A real house. Hidden faults. Your call.</p>
</header>
</section>

<section class="slide" id="why">
<ul class="tiles facts">{facts}</ul>
</section>

<section class="slide" id="hard">
<h2>Maths is all on the page. Pipes aren&rsquo;t.</h2>
<div class="three">
  <figure class="card">{_img(*pics["hidden"], "Under a kitchen basin: every pipe looks fine")}
    <figcaption><b>The fault is hidden</b><span>This trap is blocked.</span></figcaption></figure>
  <figure class="card"><div class="pair">{_img(p["before"][0], p["before"][1], p["before"][2], "Kitchen basin before running the tap")}
      {_img(p["after"][0], p["after"][1], p["after"][2], "The same basin after: the water rose instead of draining")}</div>
    <figcaption><b>Only a test shows it</b><span><code>{ESC(p["cmd"])}</code> and the water rises.</span></figcaption></figure>
  <figure class="card">{_img(*pics["puddle"], "Water on the floor under a leaking drain joint")}
    <figcaption><b>Every test has a cost</b><span>Two runs of the tap: {pics["damage"]} units of water damage.</span></figcaption></figure>
</div>
</section>

<section class="slide" id="game">
<h2>Look. Test. Fix.</h2>
<ol class="strip" aria-label="Four steps from the demo run">
{strip}
</ol>
<div class="faults">{faults}</div>
</section>
{models_slide(ladder, models)}
<section class="slide" id="harness">
<h2>Scored by replay</h2>
<ol class="flow" aria-label="How a run is scored">
  <li><b>Agent</b><span>any model, any harness</span></li>
  <li class="link"><code>{len(tools)} MCP tools</code><span aria-hidden="true">&harr;</span><code>picture + text</code></li>
  <li><b>House</b><span>simulator + renderer</span></li>
  <li class="link"><code>action log</code><span aria-hidden="true">&rarr;</span></li>
  <li><b>Verifier</b><span>replays it from the seed</span></li>
  <li class="link"><span aria-hidden="true">&rarr;</span></li>
  <li class="score"><b>Score 0&ndash;1</b></li>
</ol>
{reward_bar()}
{validity(ladder)}
<pre class="cmd"><code>harbor run --repo valuhaka/plumberbench -d plumberbench-hard -a opencode -m MODEL</code></pre>
</section>

<section class="slide end" id="try">
<div class="appicon small">{icon("gend")}</div>
<h2>Try it</h2>
<p class="try-copy">Take the tools for a spin. The hosted bench gives you a fresh house to diagnose and repair.</p>
<div class="actions"><a class="button primary" href="{PLAY}">Start a house <span aria-hidden="true">&rarr;</span></a><a class="button" href="{DEMO}">Watch the run</a><a class="button" href="{REPO}">Explore the code</a></div>
<p class="fine">Junction 2026 &middot; AfterQuery, Break the Agent</p>
<p class="fine sources">Sources: {sources}</p>
</section>
"""
    return (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>PlumberBench</title>\n'
            f'<meta name="description" content="{ESC(DESCRIPTION)}">\n'
            f'<link rel="canonical" href="{SITE}/">\n'
            f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(icon("fav").replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1))}">\n'
            f'<meta property="og:type" content="website">\n<meta property="og:url" content="{SITE}/">\n'
            f'<meta property="og:title" content="PlumberBench: AI can solve any maths problem. It can\'t fix your leaky pipes. Yet.">\n'
            f'<meta property="og:description" content="{ESC(DESCRIPTION)}">\n'
            f'<meta property="og:image" content="{SITE}/{frames[0]["src"]}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<style>{CSS}</style></head><body>\n<main>{body}</main>\n'
            f'<div class="tip" id="tip" role="tooltip" hidden></div>\n<script>{JS}</script>\n</body></html>\n')



def offline_page() -> str:
    """/play while the online server is not deployed: how to play on your own machine."""
    return (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Play PlumberBench</title>\n'
            f'<meta name="robots" content="noindex">\n<style>{CSS}</style></head><body>\n<main>\n'
            f'<section class="slide end">\n<div class="appicon small">{icon("goff")}</div>\n'
            f'<h2>Play it on your machine</h2>\n<pre class="cmd"><code>{LOCAL_PLAY}</code></pre>\n'
            f'<p class="fine">Online play is off right now.</p>\n'
            f'<div class="actions"><a class="button primary" href="/{DEMO}">Watch a run</a>'
            f'<a class="button" href="/">PlumberBench</a></div>\n</section>\n</main>\n</body></html>\n')


CSS = r"""
:root {
  --ui: "Lucida Grande", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --mono: Menlo, Monaco, "DejaVu Sans Mono", Consolas, monospace;
  --ink: #1f2328; --muted: #5f6670; --line: #d9dbde; --card: #ffffff; --accent: #2a6fcb;
  color-scheme: light;
}
* { box-sizing: border-box; }
html { background: #f3f3f2; scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
body { margin: 0; color: var(--ink); font: 15px/1.5 var(--ui); background: #f3f3f2; }
main { padding: 0 20px 24px; }
a { color: var(--accent); }
a:focus-visible, .hit:focus-visible, summary:focus-visible { outline: 3px solid #9cc0ec; outline-offset: 2px; }

.slide { max-width: 1100px; margin: 0 auto; padding: 28px 0; display: grid; justify-items: center; gap: 16px; text-align: center; }
.slide h2 { margin: 0; font: 700 clamp(24px, 3vw, 32px)/1.2 var(--ui); text-wrap: balance; }
.fine { margin: 0; color: var(--muted); font-size: 12.5px; }
.fine a { color: inherit; }
code { font: 12px/1.3 var(--mono); color: var(--ink); background: #f6f6f6; border: 1px solid #dcdcdc; border-radius: 4px; padding: 2px 7px; white-space: nowrap; }
img { display: block; width: 100%; height: auto; border-radius: 6px; border: 1px solid #e2e2e2; background: #fff; }
.card { margin: 0; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px; }

/* hero */
.hero-slide { padding-top: 14px; }
.site { display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%; height: 40px;
  padding: 0 0 0 14px; border-radius: 8px; overflow: hidden; background: #fff; border: 1px solid var(--line); }
.brand { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; color: var(--ink); text-decoration: none; }
.brand svg { width: 22px; height: 22px; display: block; }
.links { display: flex; align-self: stretch; }
.links a { display: flex; align-items: center; padding: 0 18px; color: var(--ink); text-decoration: none; font-size: 13.5px; }
.links a:hover { background: #f2f4f7; }
.links a:focus-visible { outline-offset: -3px; }
.hero { width: 100%; padding: 26px 0 4px; display: grid; justify-items: center; gap: 18px; }
h1 { margin: 0; font: 700 clamp(28px, 4.2vw, 46px)/1.15 var(--ui); text-wrap: balance; }
h1 span { color: #2a6fcb; }
.versus { width: min(100%, 860px); display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: stretch; }
.proof { display: grid; align-content: center; justify-items: center; gap: 6px; padding: 18px; color: var(--ink); text-decoration: none;
  font-family: var(--mono); background: #fff; }
.proof b { font: 700 clamp(44px, 7vw, 72px)/1 var(--ui); }
.proof span { max-width: 26ch; color: var(--muted); font: 13.5px/1.4 var(--ui); }
.appicon { width: 64px; height: 64px; filter: drop-shadow(0 2px 3px rgba(0,0,0,.18)); }
.appicon svg { width: 100%; height: 100%; display: block; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
.button { font: 14px/1 var(--ui); padding: 10px 20px; border-radius: 7px; border: 1px solid #c9cbcf; background: #fff; color: var(--ink); text-decoration: none; }
.button:hover { background: #f4f5f7; }
.button.primary { background: var(--accent); border-color: #255fae; color: #fff; }
.button.primary:hover { background: #2563b6; }

/* numbers */
.tiles { list-style: none; margin: 0; padding: 0; width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.tiles li { display: grid; gap: 4px; justify-items: center; align-content: start; padding: 14px 12px; background: var(--card); border: 1px solid var(--line); border-radius: 10px; }
.tiles b { font-size: clamp(26px, 3.4vw, 36px); line-height: 1.1; font-variant-numeric: tabular-nums; }
.tiles span { color: var(--muted); font-size: 13.5px; max-width: 30ch; }

/* why it is hard */
.three { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.three .card { display: grid; gap: 10px; grid-template-rows: 1fr auto; }
.three .pair { align-self: center; }
.three figcaption { display: grid; gap: 2px; }
.three figcaption b { font-size: 16px; }
.three figcaption span { color: var(--muted); font-size: 13.5px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; align-items: center; }

/* the game */
.strip { list-style: none; margin: 0; padding: 0; width: 100%; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.strip li { display: grid; gap: 6px; justify-items: center; align-content: start; }
.faults { width: 100%; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.faults figure { margin: 0; display: grid; gap: 6px; justify-items: center; }
.faults code { font-size: 11px; }

/* results */
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 16px; font-size: 12.5px; color: var(--muted); }
.legend li { display: inline-flex; align-items: center; gap: 7px; }
.key { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.key.line { width: 16px; height: 2px; border-radius: 0; }
.key.ring { box-shadow: inset 0 0 0 2px #3d434b; }
.key.line.dash { background: repeating-linear-gradient(90deg, #9a9a9a 0 5px, transparent 5px 8px) !important; }
.reward + .legend .key { border-radius: 3px; }
.chart-wrap { width: 100%; overflow-x: auto; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 8px 8px; }
.chart { display: block; width: 100%; min-width: 640px; height: auto; font-family: var(--ui); }
.chart .grid { stroke: #e8e8e8; stroke-width: 1; }
.chart .tick { font-size: 11px; fill: var(--muted); }
.chart .lv { font-size: 13px; font-weight: 700; fill: var(--ink); }
.chart path { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.chart .model { stroke-width: 2.5; }
.chart .base { stroke-width: 1.5; }
.chart .mean { stroke-width: 2.5; stroke-linecap: round; }
.chart .sep { stroke: #d9dbde; stroke-width: 1; }
.chart .dash { stroke-dasharray: 6 5; }
.chart .hit { fill: transparent; }
.chart .hit:hover, .chart .hit:focus { fill: rgba(42,111,203,.10); outline: none; }
.tip { position: fixed; z-index: 10; pointer-events: none; background: #fff; border: 1px solid var(--line); border-radius: 8px;
  box-shadow: 0 6px 18px rgba(0,0,0,.12); padding: 7px 10px; font-size: 12px; color: var(--muted); text-align: left; max-width: 260px; }
.tip div:first-child { font-size: 15px; font-weight: 700; color: var(--ink); }
.models { max-width: 100%; overflow-x: auto; }
.models table { border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 10px; font-size: 13px; font-variant-numeric: tabular-nums; }
.models th, .models td { padding: 6px 12px; text-align: left; border-top: 1px solid #ececec; white-space: nowrap; }
.models thead th { color: var(--muted); font-weight: 400; border-top: 0; }
.models .dim, .models td span { color: var(--muted); }

/* harness */
.flow { list-style: none; margin: 0; padding: 0; display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 8px; }
.flow > li:not(.link) { display: grid; gap: 2px; padding: 10px 14px; background: var(--card); border: 1px solid var(--line); border-radius: 10px; min-width: 120px; }
.flow > li b { font-size: 15px; }
.flow > li span { font-size: 12px; color: var(--muted); }
.flow .link { display: grid; justify-items: center; gap: 4px; color: var(--muted); font-size: 22px; line-height: 1; }
.flow > li.score { background: #eaf2fc; border-color: #b9d2f1; }
.reward { width: min(100%, 760px); display: flex; align-items: center; gap: 10px; }
.reward .bar { flex: 1; display: flex; gap: 2px; height: 26px; }
.reward .part { display: flex; align-items: center; padding: 0 8px; border-radius: 4px; font-size: 12px; font-weight: 700; min-width: 0; white-space: nowrap; }
pre.cmd { margin: 0; max-width: 100%; overflow-x: auto; }
pre.cmd code { display: inline-block; font-size: 12.5px; padding: 8px 14px; background: #fff; }
.end { padding-bottom: 28px; }
.sources { max-width: 70ch; }

@media (max-width: 860px) {
  .three, .tiles { grid-template-columns: 1fr; }
  .versus { gap: 8px; }
  .proof { padding: 10px; }
  .proof b { font-size: 34px; }
  .proof span { font-size: 12px; }
  .strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .faults { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .flow { flex-direction: column; }
  .flow .link > span { display: inline-block; transform: rotate(90deg); }
}
@media (max-width: 420px) { .brand span { display: none; } .links a { padding: 0 11px; } .reward .part { padding: 0 4px; font-size: 11px; } }

/* Pitch deck: confident editorial type, warm paper, and clear ways into the product. */
:root { --ink: #17282b; --muted: #5f706d; --line: #d5d9ce; --card: #fffef9; --accent: #15796f; }
html, body { background: #f2f0e7; }
body { font-size: 16px; }
main { padding: 0 30px 56px; }
.slide { max-width: 1160px; min-height: 84vh; padding: clamp(54px, 8vw, 104px) 0; gap: 26px; }
.hero-slide { min-height: 100vh; padding-top: 18px; }
.site { height: 58px; padding-left: 18px; border-radius: 999px; background: rgb(255 254 249 / .9); border-color: #d8dbd0; }
.brand { letter-spacing: -.03em; }
.brand svg { width: 29px; height: 29px; }
.links a { padding: 0 20px; font-size: 14px; }
.hero { padding: clamp(34px, 6vw, 66px) 0 0; gap: 24px; }
.eyebrow { margin: 0; display: inline-flex; align-items: center; gap: 9px; color: #4d6b66; text-transform: uppercase; letter-spacing: .13em; font-size: 11px; font-weight: 750; }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: #36a883; box-shadow: 0 0 0 4px #d8eee1; }
h1 { font-size: clamp(36px, 6.6vw, 76px); line-height: 1.03; letter-spacing: -.065em; }
h1 span { color: #15796f; }
.versus { width: min(100%, 1000px); gap: 18px; }
.versus > .card { min-height: 300px; border-radius: 20px; border-color: #d8dbd0; box-shadow: 0 14px 36px rgb(28 48 41 / .06); }
.versus figure { padding: 12px; }
.versus figure img { height: 100%; object-fit: cover; border: 0; border-radius: 13px; }
.proof { gap: 14px; background: #e5eee5; }
.proof b { color: #15796f; font-size: clamp(60px, 9vw, 104px); letter-spacing: -.08em; }
.proof span { max-width: 29ch; font-size: 16px; }
.actions { gap: 12px; }
.button { padding: 15px 24px; border-radius: 999px; font-size: 15px; font-weight: 650; transition: transform .18s ease, background .18s ease, box-shadow .18s ease; }
.button:hover { transform: translateY(-2px); background: white; box-shadow: 0 8px 20px rgb(28 48 41 / .1); }
.button.primary { background: #15796f; border-color: #15796f; box-shadow: 0 8px 18px rgb(21 121 111 / .18); }
.button.primary:hover { background: #0e655d; }
.hero-note { font-size: 13px; letter-spacing: .02em; }
.slide h2 { font-size: clamp(30px, 4.5vw, 48px); letter-spacing: -.055em; }
.tiles li, .three .card, .chart-wrap { border-color: #d8dbd0; border-radius: 18px; box-shadow: 0 12px 30px rgb(28 48 41 / .04); }
.tiles li { padding: 25px 18px; }
.tiles b { color: #15796f; letter-spacing: -.06em; }
.three .card { padding: 14px; }
img { border-color: #e4e4db; border-radius: 11px; }
.strip { gap: 16px; }
.strip li { padding: 10px; background: #fffef9; border: 1px solid #d8dbd0; border-radius: 16px; }
.strip code { margin: 3px 0 5px; }
.faults figure { padding: 7px; border: 1px solid #d8dbd0; border-radius: 14px; background: #fffef9; }
.faults img { border-radius: 9px; }
.flow > li:not(.link) { border-radius: 14px; padding: 14px 18px; }
.flow > li.score { background: #deeee5; border-color: #b5d9c8; }
.end { min-height: 70vh; margin-top: 20px; padding: clamp(48px, 7vw, 84px) 22px; border-radius: 28px; color: #f8f5e9; background: #183b38; }
.end h2 { color: inherit; }
.end .appicon { filter: none; }
.end .fine { color: #bdcfbf; }
.end .fine a { color: inherit; }
.try-copy { max-width: 48ch; margin: 0; color: #d4e2d7; font-size: 19px; }
.end .button { color: var(--ink); }
.end .button.primary { color: white; background: #2c9a85; border-color: #2c9a85; }
.end .button:hover { background: white; }
.sources { margin-top: 8px; }
@media (max-width: 860px) {
  main { padding: 0 18px 32px; }
  .slide { min-height: auto; padding: 58px 0; }
  .hero-slide { min-height: 92vh; }
  .versus > .card { min-height: 220px; }
  .end { padding: 54px 20px; }
}
@media (max-width: 560px) {
  .site { height: 50px; padding-left: 12px; }
  .links a { padding: 0 9px; font-size: 12px; }
  h1 { font-size: clamp(36px, 10vw, 52px); }
  .versus { grid-template-columns: 1fr; }
  .versus > .card { min-height: 190px; }
  .actions { width: 100%; }
  .actions .button { flex: 1 1 auto; text-align: center; padding: 14px 15px; }
  .end { margin-left: -2px; margin-right: -2px; border-radius: 22px; }
}
@media (prefers-reduced-motion: reduce) { .button { transition: none; } .button:hover { transform: none; } }
"""

JS = r"""
(function () {
  const tip = document.getElementById("tip");
  const show = t => {
    tip.replaceChildren(...t.dataset.tip.split("\n").map(line => { const d = document.createElement("div"); d.textContent = line; return d; }));
    tip.hidden = false;
    const r = t.getBoundingClientRect(), w = tip.offsetWidth;
    tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
    tip.style.top = Math.max(8, r.top + 8) + "px";
  };
  const hide = () => { tip.hidden = true; };
  document.querySelectorAll("[data-tip]").forEach(t => {
    t.addEventListener("pointerenter", () => show(t)); t.addEventListener("focus", () => show(t));
    t.addEventListener("pointerleave", hide); t.addEventListener("blur", hide);
  });
  addEventListener("scroll", hide, {passive: true});
  /* Presenting: the left and right arrows step from section to section. */
  const slides = [...document.querySelectorAll(".slide")];
  addEventListener("keydown", e => {
    const dir = {ArrowRight: 1, ArrowLeft: -1}[e.key];
    if (!dir || e.altKey || e.metaKey || e.ctrlKey || e.target.closest("input, textarea, select")) return;
    let i = 0;
    slides.forEach((s, k) => { if (s.offsetTop <= scrollY + innerHeight / 3) i = k; });
    slides[Math.max(0, Math.min(slides.length - 1, i + dir))].scrollIntoView({block: "start"});
    e.preventDefault();
  });
})();
"""
