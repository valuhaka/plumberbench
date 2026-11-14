"""Browser play page: a local front-end over the same episode as the terminal.

    python -m plumberbench.play --seed 3 --level 2 --web

Rules that keep it honest (tests/test_views.py enforces them):

  - Every action is a typed command line sent to `play.handle`, the same
    function the terminal uses. Buttons and menus only write those lines.
  - A response carries `text`, `image`, `hotspots` and `result`, nothing else.
    Text and image are exactly what the agent gets for that call. Hotspots are
    the boxes of the tag labels already drawn on the picture. `result` is empty
    until the job is over, then the same full result the terminal prints.
  - The page itself is static: the same bytes for every house and every state.
    Everything it says about the task is quoted from the agent's instruction or
    from the terminal's `help` (costs, fault types), and menus depend only on a
    part's kind (its tag letter), never on its state.

Styling follows the conventions of valuhaka/hoitoonohjaus (style.md): square
boxes, buttons with a slanted right edge (flat, no light effect), dialogs as
windows with a title bar, and the status in a box like its status bar, here
stacked top to bottom. The palette is water blue. The layout has two columns
on wide screens and one on narrow ones (tests/test_page_layout.py).

This server is for local play only and is never part of a Harbor task.
"""
from __future__ import annotations

import base64
import json
import threading
import webbrowser

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .env import Episode
from .play import Reply, handle
from .world import COST, DIAGNOSES, DIAGNOSIS_TEXT

ROUTES = ("/", "/history", "/command")
PAYLOAD_KEYS = ("text", "image", "hotspots", "result")

# Sentences the page shows about the task. Each is quoted word for word from the
# agent's instruction (the test checks), so the page tells people nothing more.
MORE_THAN_ONE = "There may be more than one fault."
HOUSE_TEST = ("the house is tested: every tap must run full on hot and cold, every basin must drain, "
              "nothing may drip, every part must be refitted, and no valve may be left more closed "
              "than you found it (unless that valve was itself a fault).")
FORMULA = "score = repair x (0.70 + 0.15 x dryness + 0.10 x time left + 0.05 x diagnosis)"
NOTHING_FIXED = "Fixing nothing scores 0, whatever else you do."
FROM_INSTRUCTION = (MORE_THAN_ONE, HOUSE_TEST, FORMULA, NOTHING_FIXED)

KINDS = {"V": "valve", "J": "joint", "T": "trap", "C": "cleanout plug", "A": "aerator"}

# What a click on a tag offers, by the tag's letter: (label, command template, cost).
MENUS = {
    "V": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Turn to open", "set_valve {tag} open", COST["set_valve"]),
          ("Turn to half", "set_valve {tag} half", COST["set_valve"]),
          ("Turn to closed", "set_valve {tag} closed", COST["set_valve"])],
    "J": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Put the bucket under it", "place_bucket {tag}", COST["place_bucket"]),
          ("Tighten", "repair {tag} tighten", COST["repair"]),
          ("Undo the joint", "open_joint {tag}", COST["open_joint"]),
          ("Refit with a new washer", "close_joint {tag}", COST["close_joint"])],
    "T": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Put the bucket under it", "place_bucket {tag}", COST["place_bucket"]),
          ("Remove the trap", "open_joint {tag}", COST["open_joint"]),
          ("Clear", "repair {tag} clear", COST["repair"]),
          ("Refit with a new washer", "close_joint {tag}", COST["close_joint"])],
    "C": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Put the bucket under it", "place_bucket {tag}", COST["place_bucket"]),
          ("Take out the plug", "open_joint {tag}", COST["open_joint"]),
          ("Clear", "repair {tag} clear", COST["repair"]),
          ("Refit with a new washer", "close_joint {tag}", COST["close_joint"])],
    "A": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Clear", "repair {tag} clear", COST["repair"])],
}
ROOMS = [("kitchen", "Kitchen"), ("bathroom", "Bathroom"), ("utility", "Utility room")]
VIEWS = {"kitchen": [("counter", "Counter"), ("under_sink", "Under the sink")],
         "bathroom": [("counter", "Counter"), ("under_sink", "Under the sink")],
         "utility": [("wall", "Wall of pipes")]}
STATIC = {
    "menus": MENUS, "kinds": KINDS, "rooms": ROOMS, "views": VIEWS,
    "faults": [[d, d.replace("_", " ").capitalize(), DIAGNOSIS_TEXT[d]] for d in DIAGNOSES],
    "cost": {"go": COST["go"], "look": COST["look"]},
    "text": {"more": MORE_THAN_ONE, "test": HOUSE_TEST, "formula": FORMULA, "nothing": NOTHING_FIXED},
}


def payload(reply: Reply) -> dict:
    return {
        "text": reply.text,
        "image": base64.b64encode(reply.image).decode() if reply.image else None,
        "hotspots": reply.hotspots,
        "result": reply.result,
    }


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>PlumberBench</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=Cabin:wght@400;500;600;700&display=swap');
:root {
  --accent-light: #8fc1e3; --accent: #1f6fb2; --accent-dark: #0e4a7e; --tint: #e9f2f9;
  --bg: #f4f7f9; --surface: #ffffff; --text: #17232d; --muted: #51606b; --border: #d2dee6;
  --danger: #b42318; --ok: #18794e;
  --font: 'Cabin', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --mono: ui-monospace, 'SF Mono', Menlo, monospace;
  --slant: 0.55rem; --gutter: 1.5rem; --topbar-h: 3.6rem;
  --shadow-raised: 0 0 0 1px rgb(8 30 50 / 0.03), 0 1px 2px rgb(8 30 50 / 0.06), 0 12px 28px -16px rgb(8 30 50 / 0.3);
  --shadow-window: 0 0 0 1px rgb(8 30 50 / 0.08), 0 28px 64px -24px rgb(8 30 50 / 0.5);
  --shadow-inset: inset 0 1px 2px rgb(8 30 50 / 0.12);
  --chrome-top: #fbfdfe; --chrome-bottom: #e5eef4;
  font-family: var(--font); color: var(--text); background: var(--bg);
}
* { box-sizing: border-box; border-radius: 0; }
body { margin: 0; }
h1, h2, h3 { margin: 0; font-weight: 600; }
[hidden] { display: none !important; }

/* Top bar: frosted, accent line below */
.topbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  min-height: var(--topbar-h); padding: 0.5rem var(--gutter); border-bottom: 3px solid var(--accent);
  background: rgb(255 255 255 / 0.85); -webkit-backdrop-filter: saturate(1.5) blur(14px); backdrop-filter: saturate(1.5) blur(14px); }
.brand { font-size: 1.35rem; font-weight: 700; color: var(--accent-dark); }

/* The job: the complaint, and the button to report it done */
.job { display: flex; flex-wrap: wrap; gap: 0.75rem 1.5rem; align-items: center; padding: 0.9rem var(--gutter);
  color: #fff; background: var(--accent-dark); }
.job-text { flex: 1 1 22rem; min-width: 0; }
/* Pinned under the top bar where the screen has room for it; on phones it scrolls away. */
@media (min-width: 961px) and (min-height: 700px) { .job { position: sticky; top: var(--topbar-h); z-index: 15; } }
.job-label { font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent-light); }
.complaint { font-size: clamp(1.1rem, 1rem + 0.8vw, 1.5rem); font-weight: 600; line-height: 1.3; margin: 0.15rem 0 0; }

/* Layout: picture and output on the left; status, moves and controls on the right.
   One column on narrow screens: status first, then the picture, then the controls. */
.layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(270px, 360px); grid-template-rows: auto 1fr;
  grid-template-areas: "view info" "view controls"; gap: 1.25rem 1.5rem; align-items: start;
  max-width: 1320px; margin: 0 auto; padding: 1.25rem var(--gutter) 2rem; }
.view-col { grid-area: view; min-width: 0; width: 100%; justify-self: center;
  /* The picture shrinks with the window's height so the output under it stays in view. */
  max-width: min(800px, max(440px, calc((100dvh - 23rem) * 4 / 3))); }
.infobox { grid-area: info; }
.controls { grid-area: controls; min-width: 0; }
@media (max-width: 960px) {
  :root { --gutter: 1rem; }
  .layout { grid-template-columns: minmax(0, 1fr); grid-template-rows: none; grid-template-areas: "info" "view" "controls"; gap: 1rem; }
  .view-col { max-width: 800px; }
}
.panel { background: var(--surface); border: 1px solid var(--border); padding: 1.1rem 1.25rem; box-shadow: var(--shadow-raised); }
.panel + .panel { margin-top: 1rem; }
.panel h2 { font-size: 1.05rem; color: var(--accent-dark); margin-bottom: 0.75rem; }

/* Buttons: straight left edge, slanted right edge, flat fills (two clipped layers: border, fill) */
button { --btn-bg: transparent; --btn-border: var(--btn-bg); --btn-fg: inherit; --btn-line: 1px;
  --shape: polygon(0 0, 100% 0, calc(100% - var(--slant)) 100%, 0 100%);
  position: relative; isolation: isolate; display: inline-flex; align-items: center; justify-content: center; gap: 0.5rem;
  font: inherit; font-weight: 500; cursor: pointer; padding: 0.55rem calc(1.2rem + var(--slant) / 2) 0.55rem 1.2rem;
  background: none; border: 0; color: var(--btn-fg); }
button::before, button::after { content: ''; position: absolute; z-index: -1; clip-path: var(--shape); }
button::before { inset: 0; background: var(--btn-border); }
button::after { inset: var(--btn-line); background: var(--btn-bg); }
button:active:not(:disabled)::after { background: color-mix(in srgb, var(--btn-bg) 90%, #000); }
button:focus-visible { outline: none; --btn-border: var(--accent); --btn-line: 2px; }
button:disabled { opacity: 0.5; cursor: default; }
.primary { --btn-bg: var(--accent-dark); --btn-fg: #fff; }
.primary:hover:not(:disabled) { --btn-bg: var(--accent); }
.secondary { --btn-bg: #f1f6fa; --btn-border: #c3d4e0; --btn-fg: var(--text); }
.secondary:hover:not(:disabled) { --btn-border: var(--accent-light); --btn-bg: #e6f0f8; }
.on-dark { --btn-bg: #ffffff; --btn-border: #ffffff; --btn-fg: var(--accent-dark); font-weight: 700; font-size: 1.05rem;
  padding: 0.75rem calc(1.5rem + var(--slant) / 2) 0.75rem 1.5rem; white-space: nowrap; }
.on-dark:hover:not(:disabled) { --btn-bg: #dcebf7; --btn-border: #dcebf7; }
button.link { padding: 0.15rem 0.25rem; color: var(--accent-dark); font-size: 0.9rem; }
button.link::before, button.link::after, button.plain::before, button.plain::after { content: none; }
button.link:focus-visible { outline: 2px solid var(--accent); }

/* Move: big joined segments "|Kitchen/ /Bathroom/ /Utility room/" with what each costs */
.segments { display: flex; margin-bottom: 0.9rem; }
.segments button { --btn-bg: #f1f6fa; --btn-border: #c3d4e0; --btn-fg: var(--text);
  flex: 1 1 0; min-width: 0; flex-direction: column; gap: 0.1rem; font-size: 1.05rem; font-weight: 600; line-height: 1.2;
  padding: 0.7rem calc(0.6rem + var(--slant) / 2) 0.65rem 0.6rem; text-align: center; }
.segments button + button { --shape: polygon(var(--slant) 0, 100% 0, calc(100% - var(--slant)) 100%, 0 100%);
  margin-left: calc(3px - var(--slant)); padding-left: calc(0.6rem + var(--slant) / 2); }
.segments button small { font-size: 0.78rem; font-weight: 500; color: var(--muted); }
.segments button.here { --btn-bg: var(--accent-dark); --btn-fg: #fff; --btn-border: var(--accent-dark); cursor: default; opacity: 1; }
.segments button.here small { color: var(--accent-light); }
.segments button:hover:not(:disabled):not(.here) { --btn-border: var(--accent-light); }
.choice { display: flex; }
.choice button { --btn-bg: #f1f6fa; --btn-border: #c3d4e0; padding: 0.5rem calc(0.85rem + var(--slant) / 2) 0.5rem 0.85rem; }
.choice button + button { --shape: polygon(var(--slant) 0, 100% 0, calc(100% - var(--slant)) 100%, 0 100%);
  margin-left: calc(3px - var(--slant)); padding-left: calc(0.85rem + var(--slant) / 2); }
.choice button.on { --btn-bg: var(--accent-dark); --btn-fg: #fff; --btn-border: var(--accent-dark); }
.row { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.55rem; }
.note { color: var(--muted); font-size: 0.875rem; margin: 0 0 0.9rem; }
select { font: inherit; padding: 0.5rem 0.6rem; border: 1px solid var(--border); background: var(--surface); color: var(--text); box-shadow: var(--shadow-inset); }
select:focus, input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }

/* Status: like a status bar, items stacked top to bottom, separated by grooves */
.infobox { border: 1px solid var(--border); background: linear-gradient(var(--chrome-top), var(--chrome-bottom));
  box-shadow: inset 0 1px 0 #fff, var(--shadow-raised); font-size: 0.95rem; color: var(--muted); }
.infobox > div { display: grid; grid-template-columns: 6.5rem 1fr; align-items: center; gap: 0.6rem; padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border); box-shadow: 0 1px 0 #fff; }
.infobox > div:last-child { border-bottom: 0; box-shadow: none; }
.infobox b { color: var(--text); font-weight: 600; }
.infobox .val { display: flex; align-items: center; gap: 0.6rem; min-width: 0; }
.meter { flex: 1; max-width: 140px; height: 8px; background: #dfe8ee; box-shadow: var(--shadow-inset); }
.meter > span { height: 100%; width: 0; background: var(--accent); }
.meter.damage > span { background: var(--danger); }
@media (max-width: 960px) {
  .infobox { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); }
  .infobox > div:last-child { border-bottom: 1px solid var(--border); }
}

/* The picture, with clickable tag labels */
#stage { position: relative; width: 100%; aspect-ratio: 4 / 3; background: #0b0d10; border: 1px solid var(--border); box-shadow: var(--shadow-raised); }
#view { width: 100%; height: 100%; display: block; }
.hot { position: absolute; padding: 0; outline: 2px solid transparent; cursor: pointer; }
.hot:hover, .hot:focus-visible { outline-color: var(--accent); background: rgb(31 111 178 / 0.12); }
.menu { position: absolute; z-index: 5; width: min(260px, calc(100% - 16px)); background: var(--surface); border: 1px solid var(--border);
  border-top: 3px solid var(--accent); box-shadow: var(--shadow-window); }
.menu .titlebar { padding: 0.45rem 0.8rem; }
.menu .item { display: flex; justify-content: space-between; gap: 1rem; width: 100%; padding: 0.55rem 0.8rem; text-align: left;
  border-top: 1px solid var(--border); }
.menu .item:hover, .menu .item:focus-visible { background: var(--tint); outline: none; }
.menu .item span:last-child { color: var(--muted); font-size: 0.85rem; white-space: nowrap; }

/* Output: plain monospace output, the command line at its foot, history in the corner.
   A click anywhere in it puts the cursor on the command line. */
.console { margin-top: 1rem; background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-raised);
  font: 13.5px/1.55 var(--mono); cursor: text; }
.console:focus-within { border-color: var(--accent-light); }
.console-head { display: flex; justify-content: flex-end; padding: 0.2rem 0.4rem 0; }
#transcript { max-height: 320px; overflow: auto; padding: 0 1rem; border-bottom: 1px dashed var(--border); }
#transcript pre, #latest { white-space: pre-wrap; word-break: break-word; margin: 0 0 0.8rem; font: inherit; }
#transcript .cmd, .prompt span { color: var(--accent-dark); font-weight: 600; }
#latest { padding: 0.1rem 1rem 0; margin: 0; }
.prompt { display: flex; gap: 0.6rem; align-items: center; padding: 0.35rem 1rem 0.7rem; }
.prompt input { flex: 1; min-width: 0; font: inherit; border: 0; padding: 0.15rem 0; background: transparent; color: var(--text); box-shadow: none; }
.prompt input:focus { outline: none; }
@media (max-width: 600px) { .console { font-size: 12px; } #latest, #transcript, .prompt { padding-left: 0.6rem; padding-right: 0.6rem; } }

/* Result: the score large, every other fact in a table */
.result .big { display: flex; align-items: baseline; gap: 0.6rem; margin-bottom: 0.25rem; }
.result .score { font-size: 4.2rem; font-weight: 700; line-height: 1; color: var(--accent-dark); }
.result .of { color: var(--muted); font-size: 1rem; }
.result .verdict { margin: 0 0 1rem; font-weight: 600; }
table.facts { width: 100%; border-collapse: collapse; font-size: 0.93rem; }
table.facts th, table.facts td { text-align: left; vertical-align: top; padding: 0.45rem 0.5rem; border-top: 1px solid var(--border); overflow-wrap: anywhere; }
table.facts th { width: 45%; color: var(--muted); font-weight: 500; }
table.facts tr.group th { color: var(--accent-dark); font-weight: 600; padding-top: 0.9rem; }
.pass { color: var(--ok); font-weight: 600; } .fail { color: var(--danger); font-weight: 600; }
details.raw { margin-top: 1rem; }
details.raw summary { cursor: pointer; color: var(--accent-dark); font-weight: 600; }
details.raw pre { max-height: 360px; overflow: auto; background: var(--bg); border: 1px solid var(--border); padding: 0.75rem;
  font: 12.5px/1.45 var(--mono); }

/* Dialogs: windows with a title bar */
.backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; padding: 1rem;
  background: rgb(8 30 50 / 0.35); -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px); }
.modal { width: 100%; max-width: 640px; max-height: calc(100dvh - 2rem); display: flex; flex-direction: column; min-width: 0;
  background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--accent); box-shadow: var(--shadow-window); }
.modal.wide { max-width: 860px; }
.titlebar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.55rem 0.6rem 0.55rem 1.25rem;
  border-bottom: 1px solid var(--border); background: linear-gradient(var(--chrome-top), var(--chrome-bottom)); box-shadow: inset 0 1px 0 #fff; }
.titlebar h2 { font-size: 1rem; color: var(--accent-dark); }
.close { font-size: 1.4rem; line-height: 1; color: var(--muted); padding: 0.2rem 0.4rem; }
.close::before, .close::after { content: none; }
.modal-body { padding: 1.2rem 1.5rem 1.5rem; overflow-y: auto; display: grid; grid-auto-rows: max-content; gap: 0.9rem; min-width: 0; }
.modal-body p { margin: 0; }
@media (max-width: 600px) { .backdrop { padding: 0.5rem; } .modal-body { padding: 1rem; } }
.actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.75rem; padding-top: 0.5rem; }
label.check { display: flex; gap: 0.75rem; align-items: flex-start; padding: 0.6rem 0.75rem; border: 1px solid var(--border); cursor: pointer; }
label.check:hover { border-color: var(--accent-light); }
label.check input { margin-top: 0.2rem; accent-color: var(--accent-dark); width: 1.05rem; height: 1.05rem; flex: none; }
label.check b { display: block; }
label.check span { color: var(--muted); font-size: 0.9rem; }
.faults { display: grid; gap: 0.45rem; }
.callout { display: grid; gap: 0.55rem; padding: 0.8rem 0.95rem; background: var(--tint); border: 1px solid var(--accent-light); }
.callout code, .rules code { font-family: var(--mono); font-size: 0.9em; overflow-wrap: anywhere; }
.rules h1 { font-size: 1.15rem; margin: 0.4rem 0; } .rules h2 { font-size: 1rem; color: var(--accent-dark); margin: 1rem 0 0.35rem; }
.rules ul { margin: 0.25rem 0; padding-left: 1.2rem; } .rules li { margin: 0.2rem 0; } .rules p { margin: 0.4rem 0; }
.rules pre, pre.cmds { background: var(--bg); border: 1px solid var(--border); padding: 0.6rem 0.75rem; overflow: auto; font: 12.5px/1.5 var(--mono); max-width: 100%; }
.help-ui { margin: 0; padding-left: 1.2rem; } .help-ui li { margin: 0.25rem 0; }
</style></head><body>
<header class="topbar"><div class="brand">PlumberBench</div><button class="secondary" id="help">Help</button></header>

<section class="job" aria-live="polite">
  <div class="job-text">
    <div class="job-label" id="joblabel">The job</div>
    <p class="complaint" id="complaint"></p>
  </div>
  <button class="on-dark" id="finish">Report job finished</button>
</section>

<main class="layout">
  <section class="view-col">
    <div id="stage"><img id="view" alt="The current view"><div id="hots"></div>
      <div class="menu" id="menu" role="menu" hidden></div></div>
    <div class="console">
      <div class="console-head"><button class="link" id="histbtn">Show history</button></div>
      <div id="transcript" hidden></div>
      <pre id="latest" aria-live="polite"></pre>
      <label class="prompt"><span>&gt;</span><input id="cmd" type="text" autocomplete="off" spellcheck="false"
        aria-label="Command"></label>
    </div>
  </section>
  <section class="infobox" aria-label="Status">
    <div><span>Step</span><b id="st-step">0</b></div>
    <div><span>Time used</span><span class="val"><b id="st-time"></b><span class="meter"><span style="display:block" id="st-timebar"></span></span></span></div>
    <div><span>Damage</span><span class="val"><b id="st-dmg"></b><span class="meter damage"><span style="display:block" id="st-dmgbar"></span></span></span></div>
    <div><span>Washers</span><b id="st-washers"></b></div>
    <div><span>Bucket</span><b id="st-bucket"></b></div>
    <div><span>Where</span><b id="st-where"></b></div>
  </section>
  <aside class="controls">
    <section class="panel result" id="result" hidden></section>
    <section class="panel" id="movepanel"><h2>Move</h2>
      <div class="segments" id="rooms"></div>
      <div class="segments" id="views"></div>
    </section>
    <section class="panel" id="waterpanel"><h2>Water and time</h2>
      <div class="row"><div class="choice" id="side"></div>
        <select id="tapticks" aria-label="How long to run the tap"></select>
        <button class="secondary" id="runtap">Run tap</button></div>
      <p class="note" id="tapnote"></p>
      <div class="row"><select id="waitticks" aria-label="How long to wait"></select>
        <button class="secondary" id="wait">Wait</button></div>
      <p class="note">Running the tap or waiting takes 1 time unit per tick.</p>
    </section>
  </aside>
</main>


<div class="backdrop" id="finishdlg" hidden><div class="modal" role="dialog" aria-modal="true" aria-labelledby="finishtitle">
  <div class="titlebar"><h2 id="finishtitle">Report the job finished</h2><button class="close" data-close>&times;</button></div>
  <div class="modal-body">
    <p id="finishintro"></p>
    <div class="faults" id="faultlist"></div>
    <div class="callout" id="finishrules"></div>
    <div class="actions"><button class="secondary" data-close>Keep working</button>
      <button class="primary" id="confirmfinish">Report and end the job</button></div>
  </div></div></div>

<div class="backdrop" id="helpdlg" hidden><div class="modal wide" role="dialog" aria-modal="true" aria-labelledby="helptitle">
  <div class="titlebar"><h2 id="helptitle">Help</h2><button class="close" data-close>&times;</button></div>
  <div class="modal-body">
    <h3>Using this page</h3>
    <ul class="help-ui">
      <li>Click a tag on the picture (V, J, T, C or A) to see what you can do with that part. You can only work on parts in the current view.</li>
      <li>Move between rooms and views with the buttons on the right. Use the tap and wait controls to test the plumbing.</li>
      <li>Every button types a command into the box under the picture; you can also type commands there yourself. Up and down arrows go through earlier commands.</li>
      <li>When everything works, use Report job finished at the top.</li>
    </ul>
    <h3>Commands</h3><pre class="cmds" id="helpcmds">Loading</pre>
    <h3>Rules</h3><div class="rules" id="helprules">Loading</div>
  </div></div></div>

<script>
const S = __STATIC__;
const $ = id => document.getElementById(id);
const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
let room = "", view = "", over = false, side = "cold", result = null;
const typed = []; let tpos = 0; const transcript = [];
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const units = n => n === 0 ? "No time" : n + (n === 1 ? " time unit" : " time units");

/* ---- the job banner ---- */
function setComplaint(text) {
  const m = /The tenant says: "(.*)"/.exec(text);
  if (m) $("complaint").textContent = "“" + m[1] + "”";
}

/* ---- status ---- */
function parseStatus(text) {
  const m = /^STATUS: step (\d+) \| time (\d+)\/(\d+) \| damage (\d+) \| (\w+)\/(\w+) \| (.*?) \| washers (\d+)/m.exec(text);
  if (!m) return;
  const [, step, t, budget, dmg, r, v, bucket, washers] = m;
  $("st-step").textContent = step;
  $("st-time").textContent = t + " of " + budget;
  $("st-timebar").style.width = (100 * t / budget) + "%";
  $("st-dmg").textContent = dmg; $("st-dmgbar").style.width = Math.min(100, 5 * dmg) + "%";
  $("st-washers").textContent = washers;
  $("st-bucket").textContent = cap(bucket);
  room = r; view = v;
  const roomName = S.rooms.find(([k]) => k === r)?.[1] || r;
  const viewName = (S.views[r] || []).find(([k]) => k === v)?.[1] || v;
  $("st-where").textContent = roomName + ", " + viewName.toLowerCase();
  drawMove();
}

/* ---- move and water ---- */
function segment(label, sub, line, here) {
  const b = el("button", {className: here ? "here" : ""}, label, el("small", {textContent: sub}));
  b.disabled = over || here;
  if (here) b.setAttribute("aria-current", "true");
  b.onclick = () => send(line);
  return b;
}
function drawMove() {
  $("rooms").replaceChildren(...S.rooms.map(([k, label]) =>
    segment(label, k === room ? "You are here" : units(S.cost.go), "go " + k, k === room)));
  $("views").replaceChildren(...(S.views[room] || []).map(([k, label]) =>
    segment(label, k === view ? "You are looking here" : units(S.cost.look), "look " + k, k === view)));
  const tap = room !== "utility";
  $("runtap").disabled = over || !tap;
  $("tapnote").textContent = tap ? "" : "There is no tap in the utility room.";
  $("tapnote").hidden = tap;
  document.querySelectorAll("#side button, #tapticks, #waitticks, #wait").forEach(e => e.disabled = over);
}
$("side").replaceChildren(...["cold", "hot", "both"].map(s => {
  const b = el("button", {textContent: cap(s), className: s === side ? "on" : ""});
  b.onclick = () => { side = s; document.querySelectorAll("#side button").forEach(x => x.classList.toggle("on", x === b)); };
  return b;
}));
for (let i = 1; i <= 5; i++) $("tapticks").add(new Option("For " + i + (i > 1 ? " ticks" : " tick"), i));
for (let i = 1; i <= 10; i++) $("waitticks").add(new Option(i + (i > 1 ? " ticks" : " tick"), i));
$("runtap").onclick = () => send(`run_tap ${side} ${$("tapticks").value}`);
$("wait").onclick = () => send(`wait ${$("waitticks").value}`);

/* ---- the picture and its tag menus ---- */
function drawPicture(p) {
  $("view").src = "data:image/jpeg;base64," + p.image;
  $("hots").replaceChildren(...p.hotspots.map(h => {
    const [x0, y0, x1, y1] = h.box;
    const b = el("button", {className: "hot plain"});
    b.setAttribute("aria-label", "Actions for " + h.tag);
    Object.assign(b.style, {left: (x0 / 8) + "%", top: (y0 / 6) + "%", width: ((x1 - x0) / 8) + "%", height: ((y1 - y0) / 6) + "%"});
    b.onclick = e => { e.stopPropagation(); openMenu(h); };
    return b;
  }));
}
function openMenu(h) {
  if (over) return;
  const m = $("menu");
  const kind = cap(S.kinds[h.tag[0]] || "part");
  m.replaceChildren(el("div", {className: "titlebar"}, el("h2", {textContent: h.tag + " · " + kind})),
    ...(S.menus[h.tag[0]] || []).map(([label, tpl, cost]) => {
      const b = el("button", {className: "item plain"}, el("span", {textContent: label}), el("span", {textContent: units(cost)}));
      b.setAttribute("role", "menuitem");
      b.onclick = () => send(tpl.replace("{tag}", h.tag));
      return b;
    }));
  m.hidden = false;
  // Next to the label, but always inside the picture.
  const stage = $("stage").getBoundingClientRect(), scale = stage.width / 800;
  const [, y0, x1] = h.box;
  const left = Math.max(4, Math.min(x1 * scale + 8, stage.width - m.offsetWidth - 4));
  const top = Math.max(4, Math.min(y0 * scale, stage.height - m.offsetHeight - 4));
  m.style.left = left + "px"; m.style.top = top + "px";
  m.querySelector(".item")?.focus();
}
const closeMenu = () => { $("menu").hidden = true; };

/* ---- output ---- */
function record(line, text) {
  transcript.push([line, text]);
  $("transcript").append(el("pre", {className: "cmd", textContent: "> " + line}), el("pre", {textContent: text}));
  $("histbtn").textContent = ($("transcript").hidden ? "Show" : "Hide") + " history (" + transcript.length + ")";
}
$("histbtn").onclick = () => {
  const t = $("transcript"); t.hidden = !t.hidden;
  $("latest").hidden = !t.hidden;  // the history already ends with the latest output
  $("histbtn").textContent = (t.hidden ? "Show" : "Hide") + " history (" + transcript.length + ")";
  if (!t.hidden) t.scrollTop = t.scrollHeight;
};

function apply(p, line) {
  if (line !== undefined) record(line, p.text);
  $("latest").textContent = p.text;
  setComplaint(p.text);
  parseStatus(p.text);
  if (p.image) drawPicture(p);
  if (p.result && !result) showResult(p.result);
  closeMenu();
}

async function send(line, quiet) {
  if (!line.trim()) return;
  if (!quiet) { typed.push(line); tpos = typed.length; }
  const r = await fetch("/command", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({line})});
  const p = await r.json();
  if (!quiet) apply(p, line);
  return p;
}
document.querySelector(".console").addEventListener("click", e => {
  if (e.target.closest("button") || getSelection().toString()) return;  // keep buttons and text selection working
  $("cmd").focus();
});
$("cmd").addEventListener("keydown", e => {
  if (e.key === "Enter") { send(e.target.value); e.target.value = ""; }
  if (e.key === "ArrowUp" && tpos > 0) { e.target.value = typed[--tpos]; e.preventDefault(); }
  if (e.key === "ArrowDown") { tpos = Math.min(typed.length, tpos + 1); e.target.value = typed[tpos] || ""; }
});

/* ---- finishing ---- */
$("finishintro").textContent = "Tick every fault type you found and fixed. " + S.text.more;
$("faultlist").replaceChildren(...S.faults.map(([key, name, what]) => el("label", {className: "check"},
  el("input", {type: "checkbox", value: key}), el("div", {}, el("b", {textContent: name}), el("span", {textContent: cap(what) + "."})))));
$("finishrules").append(el("p", {textContent: "When you report, " + S.text.test}),
  el("p", {}, el("code", {textContent: S.text.formula})), el("p", {textContent: S.text.nothing}),
  el("p", {textContent: "Reporting ends the job. No further actions are possible."}));
$("finish").onclick = () => over ? $("result").scrollIntoView({behavior: "smooth"}) : openDialog("finishdlg");
$("confirmfinish").onclick = () => {
  const picked = [...document.querySelectorAll("#faultlist input:checked")].map(c => c.value);
  closeDialogs(); send(["finish", ...picked].join(" "));
};

const LABELS = {repair: "Repair", faults_fixed: "Faults fixed", faults_total: "Faults present", left_worse: "Left worse than found",
  damage: "Damage", time_used: "Time used", time_budget: "Time budget", diagnosis_correct: "Diagnosis right",
  diagnosis_reported: "You reported", diagnosis_expected: "Fault types present",
  finished: "Reported finished", timed_out: "Ran out of time", consistent: "Score and house test agree",
  seed: "House", level: "Level", steps: "Steps"};
const faultName = key => S.faults.find(([k]) => k === key)?.[1] || key;
function fmt(v, k) {
  if (k === "diagnosis_reported" || k === "diagnosis_expected") return v.length ? v.map(faultName).join(", ") : "Nothing";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "Nothing";
  if (v && typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function showResult(r) {
  result = r; over = true;
  const rows = [];
  for (const [k, v] of Object.entries(r)) {
    if (k === "score" || k === "functional_test" || k === "faults") continue;
    rows.push(el("tr", {}, el("th", {textContent: LABELS[k] || cap(k.replace(/_/g, " "))}), el("td", {textContent: fmt(v, k)})));
  }
  if (r.functional_test) {
    rows.push(el("tr", {className: "group"}, el("th", {colSpan: 2, textContent: "House test"})));
    for (const [k, ok] of Object.entries(r.functional_test))
      rows.push(el("tr", {}, el("th", {textContent: cap(k)}), el("td", {className: ok ? "pass" : "fail", textContent: ok ? "Passed" : "Failed"})));
  }
  if (r.faults) {
    rows.push(el("tr", {className: "group"}, el("th", {colSpan: 2, textContent: "What was wrong"})));
    for (const f of r.faults) {
      const name = S.faults.find(([key]) => key === f.type)?.[1] || f.type;
      const how = f.cause || f.pos || "";
      rows.push(el("tr", {}, el("th", {textContent: name}), el("td", {textContent: f.tag + (how ? " (" + how + ")" : "")})));
    }
  }
  const verdict = r.repair === 1 ? "Every fault fixed." : "Not every fault was fixed.";
  $("result").replaceChildren(
    el("h2", {textContent: "Result"}),
    el("div", {className: "big"}, el("span", {className: "score", textContent: r.score.toFixed(2)}), el("span", {className: "of", textContent: "out of 1"})),
    el("p", {className: "verdict", textContent: verdict}),
    el("table", {className: "facts"}, el("tbody", {}, ...rows)),
    el("details", {className: "raw"}, el("summary", {textContent: "Full JSON"}), el("pre", {textContent: JSON.stringify(r, null, 2)})));
  $("result").hidden = false; $("movepanel").hidden = true; $("waterpanel").hidden = true;
  $("joblabel").textContent = "Job over";
  $("finish").textContent = "See the result";
  drawMove();
}

/* ---- dialogs ---- */
function openDialog(id) { $(id).hidden = false; $(id).querySelector("button:not([data-close]), input")?.focus(); }
function closeDialogs() { document.querySelectorAll(".backdrop").forEach(d => d.hidden = true); }
document.querySelectorAll("[data-close]").forEach(b => b.onclick = closeDialogs);
document.querySelectorAll(".backdrop").forEach(d => d.addEventListener("click", e => { if (e.target === d) closeDialogs(); }));
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeMenu(); closeDialogs(); } });
document.addEventListener("click", e => { if (!$("menu").contains(e.target)) closeMenu(); });

/* Help: the commands and the rules, fetched through the same handler the terminal uses */
function markdown(md) {
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>");
  let html = "", list = false, pre = false;
  for (const line of md.split("\n")) {
    if (line.startsWith("    ")) { if (!pre) { html += (list ? "</ul>" : "") + "<pre>"; pre = true; list = false; } html += esc(line.slice(4)) + "\n"; continue; }
    if (pre) { html += "</pre>"; pre = false; }
    if (/^- /.test(line)) { if (!list) { html += "<ul>"; list = true; } html += "<li>" + inline(line.slice(2)) + "</li>"; continue; }
    if (list && line.startsWith("  ")) { html = html.replace(/<\/li>$/, " " + inline(line.trim()) + "</li>"); continue; }
    if (list) { html += "</ul>"; list = false; }
    if (line.startsWith("## ")) html += "<h2>" + inline(line.slice(3)) + "</h2>";
    else if (line.startsWith("# ")) html += "<h1>" + inline(line.slice(2)) + "</h1>";
    else if (line.trim()) html += "<p>" + inline(line) + "</p>";
  }
  return html + (list ? "</ul>" : "") + (pre ? "</pre>" : "");
}
let helpLoaded = false;
$("help").onclick = async () => {
  openDialog("helpdlg");
  if (helpLoaded) return;
  helpLoaded = true;
  $("helpcmds").textContent = (await send("help", true)).text;
  $("helprules").innerHTML = markdown((await send("rules", true)).text);
};

/* ---- start: replay what has happened so far ---- */
fetch("/history").then(r => r.json()).then(h => {
  h.log.forEach(([line, text]) => { record(line, text); setComplaint(text); });
  apply(h.current);
});
</script></body></html>
""".replace("__STATIC__", json.dumps(STATIC))


def make_app(ep: Episode, first: Reply) -> Starlette:
    lock = threading.Lock()
    state = {"current": first, "log": [("briefing", first.text)]}

    async def page(_: Request):
        return HTMLResponse(PAGE)

    async def history(_: Request):
        return JSONResponse({"log": state["log"], "current": payload(state["current"])})

    async def command(request: Request):
        try:
            line = str((await request.json())["line"])
        except (ValueError, KeyError, TypeError):
            return JSONResponse(payload(Reply("Send {\"line\": \"<command>\"}.")), status_code=400)
        with lock:
            reply = handle(ep, line)
            state["log"].append((line, reply.text))
            if reply.image:
                state["current"] = reply
        return JSONResponse(payload(reply))

    return Starlette(routes=[Route("/", page), Route("/history", history),
                             Route("/command", command, methods=["POST"])])


def serve(ep: Episode, first: Reply, port: int, open_browser: bool = True) -> None:
    import uvicorn

    url = f"http://127.0.0.1:{port}/"
    print(f"Playing at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(make_app(ep, first), host="127.0.0.1", port=port, log_level="warning")
