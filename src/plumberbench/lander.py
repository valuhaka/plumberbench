"""The website's front page: the pitch, one screen per section, told in figures.

Built by `python -m plumberbench.demo`, from data in the repo only:
    hero frames     the demo run, each captioned with the command that made it, checked
                    against the run's log (the build fails rather than mislabel a frame)
    pictures        rendered here from the simulator: the five views, each fault's part up
                    close, and one action's before and after
    score chart     results/ladder.json (python -m plumberbench.ladder --json)
    models chart    every results/models/*.json (python -m plumberbench.results add ...)
    level rows      generate.LEVELS; the reward bar, judge's weights; the tools, play.COMMANDS

Pictures go to site/img/. When presenting, the arrow keys step from section to section.
"""
from __future__ import annotations

import html
import io
import json
import random
import statistics
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from .generate import LEVELS, generate
from .icon import icon
from .judge import REGRESSION_PENALTY, W_DRY, W_NAMED, W_QUICK, W_REPAIR
from .play import COMMANDS
from .results import stats
from .world import VIEWS

REPO = "https://github.com/valuhaka/plumberbench"
SITE = "https://plumberbench.org"
DESCRIPTION = ("An agent gets a house with hidden plumbing faults, seen only in pictures, and has to look, "
               "test, diagnose and repair. A Harbor benchmark for world models and context.")
DEMO = "demo.html"
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

# Chart colours: the validated categorical slots 1-3, and grey for the exploits (all at zero).
SERIES = [
    ("reference solver", "Reference plumber", "#2a78d6"),
    ("service all, never test", "Services everything, never tests", "#eb6834"),
    ("exploits", "Five exploits", "#9a9a9a"),
]
MODEL_COLORS = ["#1baf7a", "#eda100", "#e87ba4"]  # categorical slots 3-5, after the two policies
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
    views = []
    s = generate(7, 3)
    for room, names in VIEWS.items():
        for view in names:
            s.room, s.view = room, view
            name = f"view-{room}-{view}.jpg"
            w, h = _save(_render(s), img / name, 320)
            views.append({"src": f"img/{name}", "w": w, "h": h, "alt": f"{room}, {view.replace('_', ' ')}"})
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
    s.room, s.view = "kitchen", "counter"
    before = _save(_render(s), img / "predict-before.jpg", 400)
    sim.apply(s, tool, args)
    after = _save(_render(s), img / "predict-after.jpg", 400)
    return {"views": views, "faults": faults,
            "predict": {"cmd": command(tool, args), "before": ("img/predict-before.jpg", *before),
                        "after": ("img/predict-after.jpg", *after)}}


# ------------------------------------------------------------------ data

def load_results(results: Path) -> tuple[dict, list[dict]]:
    ladder = json.loads((results / "ladder.json").read_text())
    models = [json.loads(p.read_text()) for p in sorted((results / "models").glob("*.json"))]
    return ladder, models


def groups(ladder: dict) -> dict:
    """{level: {series key: [scores]}}, the five exploits pooled."""
    exploits = [k for k in ladder["scores"] if k not in ("reference solver", "service all, never test")]
    out = {}
    for lv in ladder["levels"]:
        key = str(lv)
        out[lv] = {"reference solver": ladder["scores"]["reference solver"][key],
                   "service all, never test": ladder["scores"]["service all, never test"][key],
                   "exploits": [x for k in exploits for x in ladder["scores"][k][key]]}
    return out


# ------------------------------------------------------------------ figures

def results_chart(ladder: dict) -> str:
    """Every house's score: one column per policy within each level, the mean as a dark tick,
    and under the plot the rows that say how each level is harder."""
    data = groups(ladder)
    levels = ladder["levels"]
    left, right, top, plot_h, width = 132, 16, 14, 270, 960
    band = (width - left - right) / len(levels)
    slot_x = {"reference solver": 0.22, "service all, never test": 0.5, "exploits": 0.78}
    y = lambda v: top + (1 - v) * plot_h
    rnd = random.Random(7)
    colors = {k: c for k, _, c in SERIES}
    names = {k: n for k, n, _ in SERIES}
    parts = []
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{left - 8}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v:g}</text>')
    for i, lv in enumerate(levels):
        x0 = left + i * band
        for key, scores in data[lv].items():
            cx = x0 + slot_x[key] * band
            jitter = band * 0.085
            for sc in scores:
                dx = rnd.uniform(-jitter, jitter)
                parts.append(f'<circle cx="{cx + dx:.1f}" cy="{y(sc):.1f}" r="2.6" fill="{colors[key]}" '
                             f'fill-opacity="0.55"/>')
            mean = statistics.mean(scores)
            parts.append(f'<line x1="{cx - jitter - 4:.1f}" x2="{cx + jitter + 4:.1f}" y1="{y(mean):.1f}" '
                         f'y2="{y(mean):.1f}" class="mean"/>')
            tip = (f"{mean:.2f} mean\n{names[key]}, level {lv}\n"
                   f"lowest {min(scores):.2f}, highest {max(scores):.2f}, "
                   f"{len(scores)} houses")
            parts.append(f'<rect x="{cx - band * 0.13:.1f}" y="{top}" width="{band * 0.26:.1f}" height="{plot_h}" '
                         f'class="hit" tabindex="0" data-tip="{ESC(tip)}" aria-label="{ESC(tip.replace(chr(10), ", "))}"/>')
        parts.append(f'<text x="{x0 + band / 2:.1f}" y="{top + plot_h + 22}" class="lv" text-anchor="middle">'
                     f'Level {lv}</text>')
    # How each level is harder, aligned with the columns above.
    rows = [("Faults", "faults", "dots"), ("Hidden behind another", "masked", "check"),
            ("Vague complaint", "vague", "check"), ("Decoys", "decoys", "rings"), ("Time budget", "budget", "number")]
    ry = top + plot_h + 52
    for r, (label, field, kind) in enumerate(rows):
        yy = ry + r * 22
        parts.append(f'<text x="{left - 8}" y="{yy + 4}" class="row" text-anchor="end">{label}</text>')
        if r:
            parts.append(f'<line x1="8" x2="{width - right}" y1="{yy - 11}" y2="{yy - 11}" class="grid"/>')
        for i, lv in enumerate(levels):
            cx = left + i * band + band / 2
            value = LEVELS[lv][field]
            if kind in ("dots", "rings"):
                for k in range(value):
                    px = cx + (k - (value - 1) / 2) * 13
                    fill = "#3a3f46" if kind == "dots" else "#ffffff"
                    parts.append(f'<circle cx="{px:.1f}" cy="{yy}" r="4.5" fill="{fill}" stroke="#3a3f46" stroke-width="1.5"/>')
                if value == 0:
                    parts.append(f'<text x="{cx:.1f}" y="{yy + 4}" class="row dim" text-anchor="middle">none</text>')
            elif kind == "check":
                parts.append(f'<path d="M{cx - 6:.1f} {yy}l4 4 8-9" class="check"/>' if value else
                             f'<text x="{cx:.1f}" y="{yy + 4}" class="row dim" text-anchor="middle">no</text>')
            else:
                parts.append(f'<text x="{cx:.1f}" y="{yy + 4}" class="row" text-anchor="middle">{value}</text>')
    height = ry + len(rows) * 22 - 6
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Score of every house by level and policy; the table below lists the same">'
            + "".join(parts) + "</svg>")


def results_table(ladder: dict) -> str:
    data = groups(ladder)
    head = "".join(f"<th>{ESC(n)}</th>" for _, n, _ in SERIES)
    rows = []
    for lv, by in data.items():
        cells = "".join(f"<td>{statistics.mean(by[k]):.2f} ({min(by[k]):.2f}–{max(by[k]):.2f})</td>" for k, _, _ in SERIES)
        rows.append(f"<tr><th>Level {lv}</th>{cells}</tr>")
    return (f'<details class="table"><summary>Table</summary><table><thead><tr><th></th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table><p>Mean (lowest–highest) over {ladder["seeds"]} houses per level; '
            f'the five exploits pooled.</p></details>')


def legend(entries: list[tuple[str, str, str]]) -> str:
    """entries: (name, colour, key class)."""
    items = "".join(f'<li><span class="key {cls}" style="background:{c}"></span>{ESC(n)}</li>' for n, c, cls in entries)
    return f'<ul class="legend">{items}</ul>'


def models_chart(ladder: dict, models: list[dict]) -> str:
    """Mean score by level: the reference plumber and the never-test policy for scale, then each
    model's mean (ringed dot) over its jobs (faint dots), joined across levels it ran in a row."""
    levels = ladder["levels"]
    left, right, top, plot_h, width = 48, 40, 14, 260, 960
    step = (width - left - right) / (len(levels) - 1)
    xpos = {lv: left + i * step for i, lv in enumerate(levels)}
    y = lambda v: top + (1 - v) * plot_h
    rnd = random.Random(11)
    parts = []
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line x1="{left - 20}" x2="{width - right + 20}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                     f'<text x="{left - 26}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v:g}</text>')
    for lv in levels:
        parts.append(f'<text x="{xpos[lv]:.1f}" y="{top + plot_h + 22}" class="lv" text-anchor="middle">Level {lv}</text>')
    series = [(name, color, {int(lv): statistics.mean(v) for lv, v in ladder["scores"][key].items()}, None)
              for key, name, color in SERIES[:2]]
    for m, color in zip(models, MODEL_COLORS):
        by = {}
        for r in m["rows"]:
            by.setdefault(r["level"], []).append(r)
        series.append((m["label"], color, {lv: statistics.mean(r["score"] for r in rs) for lv, rs in by.items()}, by))
    for name, color, means, jobs in series:
        present = [lv for lv in levels if lv in means]
        for a, b in zip(present, present[1:]):
            if levels.index(b) == levels.index(a) + 1:
                parts.append(f'<line x1="{xpos[a]:.1f}" y1="{y(means[a]):.1f}" x2="{xpos[b]:.1f}" y2="{y(means[b]):.1f}" '
                             f'stroke="{color}" stroke-width="2" stroke-linecap="round"/>')
        for lv in present:
            if jobs:
                for r in jobs[lv]:
                    parts.append(f'<circle cx="{xpos[lv] + rnd.uniform(-9, 9):.1f}" cy="{y(r["score"]):.1f}" r="2.6" '
                                 f'fill="{color}" fill-opacity="0.45"/>')
            parts.append(f'<circle cx="{xpos[lv]:.1f}" cy="{y(means[lv]):.1f}" r="5" fill="{color}" stroke="#fff" stroke-width="2"/>')
            if jobs:
                st = stats(jobs[lv])
                tip = (f"{means[lv]:.2f} mean\n{name}, level {lv}\n{st['fixed_all']} of {st['jobs']} jobs fixed every fault, "
                       f"{st['diagnosis_right']} named them right")
            else:
                tip = f"{means[lv]:.2f} mean\n{name}, level {lv}\n{ladder['seeds']} houses"
            parts.append(f'<rect x="{xpos[lv] - 14:.1f}" y="{y(means[lv]) - 14:.1f}" width="28" height="28" class="hit" '
                         f'tabindex="0" data-tip="{ESC(tip)}" aria-label="{ESC(tip.replace(chr(10), ", "))}"/>')
    height = top + plot_h + 32
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Mean score by level for the reference plumber, the never-test policy and each model">'
            + "".join(parts) + "</svg>")


def model_table(models: list[dict]) -> str:
    """Accuracy and spend per model, levels 1-2 and 3-4 apart."""
    rows = []
    for m in models:
        for name, keep in (("1–2", lambda r: r["level"] <= 2), ("3–4", lambda r: r["level"] >= 3)):
            jobs = [r for r in m["rows"] if keep(r)]
            if not jobs:
                continue
            st = stats(jobs)
            secs = f"{st['seconds']:.0f} s" if st["seconds"] else "–"
            rows.append(f"<tr><th>{ESC(m['label'])}</th><td>{name}</td><td>{st['jobs']}</td><td>{st['score']:.2f}</td>"
                        f"<td>{st['fixed_all']} of {st['jobs']}</td><td>{st['diagnosis_right']} of {st['jobs']}</td>"
                        f"<td>{st['tokens_read'] / 1000:.0f}k <span>({st['cached_share']:.0%} cached)</span></td>"
                        f"<td>{st['tokens_written'] / 1000:.1f}k</td><td>{st['tool_calls']:.0f}</td><td>{secs}</td></tr>")
    return ('<div class="models"><table><thead><tr><th>Model</th><th>Levels</th><th>Jobs</th><th>Score</th>'
            '<th>Every fault fixed</th><th>Faults named right</th><th>Tokens read per job</th><th>Written</th>'
            '<th>Tool calls</th><th>Time</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"
            + "</div>")


def early_finish(models: list[dict]) -> tuple[int, int]:
    """Model jobs at levels 3-4 that reported the job done with a fault still in the house."""
    jobs = [r for m in models for r in m["rows"] if r["level"] >= 3]
    return sum(1 for r in jobs if r.get("finished") and r.get("repair", 1) < 1), len(jobs)


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
    early, total = early_finish(models)
    entries = [(n, c, "") for _, n, c in SERIES[:2]] + [(m["label"], c, "big") for m, c in zip(models, MODEL_COLORS)]
    stat = (f'<p class="stat"><b>{early} of {total}</b><span>level 3–4 jobs reported done with a fault still in the house</span></p>') if total else ""
    return f"""
<section class="slide" id="models">
<h2>Where models break</h2>
{legend(entries)}
<div class="chart-wrap">{models_chart(ladder, models)}</div>
{stat}
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
    chips = "".join(f"<code>{ESC(t)}</code>" for t in tools)
    p = pics["predict"]
    views = "".join(_img(v["src"], v["w"], v["h"], v["alt"]) for v in pics["views"])
    faults = "".join(
        f'<figure>{_img(f["src"], f["w"], f["h"], f["kind"].replace("_", " ") + ", " + f["tag"] + " up close")}'
        f'<figcaption><code>{f["kind"]}</code></figcaption></figure>' for f in pics["faults"])

    body = f"""
<section class="slide hero-slide" id="top">
<nav class="site" aria-label="Site"><a class="brand" href="./">{icon("gnav")}<span>PlumberBench</span></a>
<span class="links"><a href="{DEMO}">Demo</a><a href="#results">Results</a><a href="{REPO}">Code</a></span></nav>
<header class="hero">
  <div class="appicon">{icon("ghero")}</div>
  <h1>What&rsquo;s the next bottleneck?</h1>
  <ol class="strip" aria-label="Four steps from the demo run">
{strip}
  </ol>
  <div class="actions"><a class="button primary" href="{DEMO}">Watch a run</a><a class="button" href="{REPO}#playing-it-yourself">Try the house</a></div>
</header>
</section>

<section class="slide" id="bottlenecks">
<div class="three">
  <figure class="cand off"><figcaption><b>Hands</b><span class="tag">not tested</span></figcaption>
    <div class="tools">{chips}</div></figure>
  <figure class="cand"><figcaption><b>World model</b><span class="tag on">tested</span></figcaption>
    <div class="pair">{_img(p["before"][0], p["before"][1], p["before"][2], "Kitchen basin before running the tap")}
      <span class="arrow"><code>{ESC(p["cmd"])}</code><span aria-hidden="true">&rarr;</span></span>
      {_img(p["after"][0], p["after"][1], p["after"][2], "The same basin after: the water rose instead of draining")}</div></figure>
  <figure class="cand"><figcaption><b>Context</b><span class="tag on">tested</span></figcaption>
    <div class="views">{views}</div></figure>
</div>
</section>

<section class="slide" id="faults">
<h2>Six faults</h2>
<div class="faults">{faults}</div>
</section>

<section class="slide" id="results">
<h2>Solvable. Not gameable.</h2>
{legend([(n, c, "") for _, n, c in SERIES] + [("Mean", "#1f1f1f", "tick")])}
<div class="chart-wrap">{results_chart(ladder)}</div>
{results_table(ladder)}
</section>
{models_slide(ladder, models)}
<section class="slide" id="harness">
<h2>Scored by replay</h2>
<ol class="flow" aria-label="How a run is scored">
  <li><b>Agent</b><span>OpenCode + model</span></li>
  <li class="link"><code>{len(tools)} MCP tools</code><span aria-hidden="true">&harr;</span><code>picture + text</code></li>
  <li><b>House</b><span>simulator + renderer</span></li>
  <li class="link"><code>action log</code><span aria-hidden="true">&rarr;</span></li>
  <li><b>Verifier</b><span>replays it from the seed</span></li>
  <li class="link"><span aria-hidden="true">&rarr;</span></li>
  <li class="score"><b>Score 0&ndash;1</b></li>
</ol>
{reward_bar()}
<pre class="cmd"><code>harbor run --repo valuhaka/plumberbench -d plumberbench -a opencode -m MODEL</code></pre>
</section>

<section class="slide end" id="try">
<div class="appicon small">{icon("gend")}</div>
<h2>Try it</h2>
<div class="actions"><a class="button primary" href="{DEMO}">Watch a run</a><a class="button" href="{REPO}#playing-it-yourself">Play the house</a><a class="button" href="{REPO}">Code</a></div>
<p class="fine">Junction 2026 &middot; AfterQuery, Break the Agent</p>
</section>
"""
    return (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>PlumberBench</title>\n'
            f'<meta name="description" content="{ESC(DESCRIPTION)}">\n'
            f'<link rel="canonical" href="{SITE}/">\n'
            f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(icon("fav").replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1))}">\n'
            f'<meta property="og:type" content="website">\n<meta property="og:url" content="{SITE}/">\n'
            f'<meta property="og:title" content="PlumberBench: what\'s the next bottleneck?">\n'
            f'<meta property="og:description" content="{ESC(DESCRIPTION)}">\n'
            f'<meta property="og:image" content="{SITE}/{frames[0]["src"]}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<style>{CSS}</style></head><body>\n<main>{body}</main>\n'
            f'<div class="tip" id="tip" role="tooltip" hidden></div>\n<script>{JS}</script>\n</body></html>\n')


CSS = r"""
:root {
  --ui: "Lucida Grande", "Lucida Sans Unicode", "Lucida Sans", Geneva, Verdana, sans-serif;
  --mono: Monaco, Menlo, "DejaVu Sans Mono", Consolas, monospace;
  --ink: #1f1f1f; --muted: #626262; --line: #c4c4c4;
  color-scheme: light;
}
* { box-sizing: border-box; }
html { background: #e3e3e3; scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
@media (min-width: 900px) and (min-height: 640px) { html { scroll-snap-type: y proximity; } }
body { margin: 0; color: var(--ink); font: 14px/1.5 var(--ui); background: linear-gradient(#f4f4f4, #e3e3e3 100vh) no-repeat, #e3e3e3; }
main { padding: 0 20px; }
a:focus-visible, .hit:focus-visible, summary:focus-visible { outline: 3px solid #7fb2ef; outline-offset: 2px; }

.slide { max-width: 1100px; margin: 0 auto; padding: 56px 0; display: grid; align-content: center;
  justify-items: center; gap: 22px; scroll-snap-align: start; text-align: center; }
/* One screen per section where it is presented; on a phone the sections simply follow each other. */
@media (min-width: 900px) and (min-height: 640px) { .slide { min-height: 100svh; padding: 64px 0; } }
.slide + .slide { border-top: 1px solid #d0d0d0; }
.slide h2 { margin: 0; font: 700 clamp(26px, 3.4vw, 36px)/1.15 var(--ui); text-wrap: balance; }
.fine { margin: 0; color: var(--muted); font-size: 12.5px; }
code { font: 12px/1.3 var(--mono); color: var(--ink); background: #fff; border: 1px solid #c9c9c9; border-radius: 4px; padding: 3px 8px; white-space: nowrap; }
img { display: block; width: 100%; height: auto; background: #fff; padding: 4px; border: 1px solid #b3b3b3; box-shadow: 0 2px 5px rgba(0,0,0,.14); }

/* hero */
.hero-slide { padding-top: 18px; gap: 0; grid-template-rows: auto 1fr; align-content: stretch; }
.site { display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%;
  padding: 0 0 0 14px; height: 36px; border-radius: 6px; overflow: hidden; color: #222; text-shadow: 0 1px 0 rgba(255,255,255,.7);
  background: linear-gradient(#f4f4f4, #d2d2d2 50%, #c4c4c4 51%, #dadada); border: 1px solid #8a8a8a; box-shadow: 0 1px 3px rgba(0,0,0,.16); }
.brand { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; color: inherit; text-decoration: none; }
.brand svg { width: 22px; height: 22px; display: block; }
.links { display: flex; align-self: stretch; }
.links a { display: flex; align-items: center; padding: 0 20px; color: inherit; text-decoration: none; font-size: 13px;
  border-left: 1px solid #a3a3a3; box-shadow: inset 1px 0 0 rgba(255,255,255,.65); }
.links a:hover { background: rgba(0,0,0,.05); }
.links a:focus-visible { outline-offset: -3px; }
.hero { width: 100%; padding: 28px 0 16px; display: grid; justify-items: center; align-content: center; gap: 14px; }
.appicon { width: 84px; height: 84px; filter: drop-shadow(0 3px 4px rgba(0,0,0,.25)); }
.appicon.small { width: 64px; height: 64px; }
.appicon svg { width: 100%; height: 100%; display: block; }
h1 { margin: 0; font: 700 clamp(28px, 4vw, 40px)/1.15 var(--ui); text-wrap: balance; }
.strip { list-style: none; margin: 18px 0 0; padding: 0; width: 100%; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.strip li { display: grid; gap: 8px; justify-items: center; align-content: start; }
.actions { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; margin-top: 14px; }
.button { font: 13px/1 var(--ui); padding: 9px 20px; border-radius: 5px; border: 1px solid #8c8c8c; background: linear-gradient(#fdfdfd, #ececec); color: #111; text-decoration: none; }
.button.primary { background: linear-gradient(#97a0ab, #6e7783); border-color: #565e68; color: #fff; }

/* three candidates */
.three { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; align-items: stretch; }
.cand { margin: 0; padding: 16px; background: #fff; border: 1px solid var(--line); border-radius: 9px; display: grid; gap: 14px; align-content: start; }
.cand figcaption { display: grid; gap: 2px; }
.cand figcaption b { font-size: 18px; }
.cand figcaption { justify-items: center; }
.tag { font-size: 11.5px; padding: 1px 8px; border-radius: 9px; background: #dcdcdc; color: #555; }
.tag.on { background: linear-gradient(#97a0ab, #6e7783); color: #fff; }
.cand.off { background: #ececec; grid-template-rows: auto 1fr; }
.cand.off b { color: #6b6b6b; }
.tools { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; align-content: center; }
.cand.off code { color: #555; }
.pair { display: grid; gap: 8px; justify-items: center; }
.pair .arrow { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); }
.pair .arrow span { display: inline-block; transform: rotate(90deg); font-size: 16px; }
.views { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.views img { padding: 2px; }
.views img:last-child { grid-column: 1 / -1; width: calc(50% - 4px); justify-self: center; }

/* faults */
.faults { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px 22px; }
.faults figure { margin: 0; display: grid; gap: 8px; justify-items: center; }

/* results */
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 18px; font-size: 12.5px; color: var(--muted); }
.legend li { display: inline-flex; align-items: center; gap: 7px; }
.key { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.key.big { width: 12px; height: 12px; box-shadow: 0 0 0 2px #fff, 0 0 0 3px #d0d0d0; }
.key.tick { width: 14px; height: 2px; border-radius: 0; background: #1f1f1f; }
.reward + .legend .key { border-radius: 3px; }
.chart-wrap { width: 100%; overflow-x: auto; background: #fff; border: 1px solid var(--line); border-radius: 9px; padding: 14px 8px 10px; }
.chart { display: block; width: 100%; min-width: 640px; height: auto; font-family: var(--ui); }
.chart .grid { stroke: #e3e3e3; stroke-width: 1; }
.chart .tick { font-size: 11px; fill: var(--muted); }
.chart .lv { font-size: 13px; font-weight: 700; fill: var(--ink); }
.chart .row { font-size: 11.5px; fill: var(--muted); }
.chart .row.dim { fill: #9a9a9a; }
.chart .mean { stroke: #1f1f1f; stroke-width: 2; stroke-linecap: round; }
.chart .check { fill: none; stroke: #3a3f46; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.chart .hit { fill: transparent; }
.chart .hit:hover, .chart .hit:focus { fill: rgba(127,178,239,.12); outline: none; }
details.table { font-size: 12.5px; color: var(--muted); max-width: 100%; }
details.table summary { cursor: pointer; color: #2a5ea3; }
details.table table { margin: 10px auto 6px; border-collapse: collapse; background: #fff; font-variant-numeric: tabular-nums; }
details.table th, details.table td { padding: 5px 10px; border: 1px solid #e0e0e0; text-align: left; color: var(--ink); }
details.table p { margin: 4px 0; }
details.table code { white-space: normal; }
.tip { position: fixed; z-index: 10; pointer-events: none; background: #fff; border: 1px solid #8a8a8a; border-radius: 6px;
  box-shadow: 0 6px 18px rgba(0,0,0,.2); padding: 7px 10px; font-size: 12px; color: var(--muted); text-align: left; max-width: 260px; }
.tip div:first-child { font-size: 15px; font-weight: 700; color: var(--ink); }

.stat { margin: 0; display: flex; flex-wrap: wrap; justify-content: center; align-items: baseline; gap: 6px 12px; text-align: left; }
.stat b { font-size: 44px; line-height: 1; white-space: nowrap; }
.stat span { max-width: 30ch; color: var(--muted); font-size: 14px; }
.models { max-width: 100%; overflow-x: auto; }
.models table { border-collapse: collapse; background: #fff; border: 1px solid var(--line); font-size: 12.5px; font-variant-numeric: tabular-nums; }
.models th, .models td { padding: 6px 10px; text-align: left; border-top: 1px solid #e3e3e3; white-space: nowrap; }
.models thead th { color: var(--muted); font-weight: 400; border-top: 0; }
.models td span { color: var(--muted); }
.models p { margin: 6px 0 0; font-size: 12px; color: var(--muted); }

/* harness */
.flow { list-style: none; margin: 0; padding: 0; display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 10px; }
.flow > li:not(.link) { display: grid; gap: 2px; padding: 12px 16px; background: #fff; border: 1px solid var(--line); border-radius: 9px; min-width: 128px; }
.flow > li b { font-size: 15px; }
.flow > li span { font-size: 12px; color: var(--muted); }
.flow .link { display: grid; justify-items: center; gap: 4px; color: #3a3f46; font-size: 26px; line-height: 1; }
.flow > li.score { background: linear-gradient(#97a0ab, #6e7783); border-color: #565e68; }
.flow > li.score b, .flow > li.score span { color: #fff; }
.reward { width: min(100%, 760px); display: flex; align-items: center; gap: 10px; }
.reward .bar { flex: 1; display: flex; gap: 2px; height: 28px; }
.reward .part { display: flex; align-items: center; padding: 0 8px; border-radius: 4px; font-size: 12px; font-weight: 700; min-width: 0; white-space: nowrap; }
pre.cmd { margin: 0; max-width: 100%; overflow-x: auto; }
pre.cmd code { display: inline-block; font-size: 12.5px; padding: 8px 14px; }

@media (max-width: 860px) {
  .strip { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 12px; }
  .three { grid-template-columns: 1fr; }
  .faults { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .flow { flex-direction: column; }
  .flow .link > span { display: inline-block; transform: rotate(90deg); }
}
@media (max-width: 420px) { .brand span { display: none; } .links a { padding: 0 12px; } .reward .part { padding: 0 4px; font-size: 11px; } }
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
