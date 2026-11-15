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

This server is for one local player; online.py serves the same page to many,
a house each. Neither is ever part of a Harbor task.
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
from .icon import icon
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
/* The pitch site's look: light flat surfaces, one blue for actions and selection, Lucida Grande. */
:root {
  --ink: #1f2328; --muted: #5f6670; --line: #d9dbde; --line-strong: #b9bcc1; --surface: #ffffff;
  --graphite: #2a6fcb; --graphite-dark: #255fae; --graphite-light: #9cc0ec; --select: #9cc0ec;
  --danger: #b42318; --ok: #18794e;
  --font: "Lucida Grande", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --mono: Menlo, Monaco, "DejaVu Sans Mono", Consolas, monospace;
  --gutter: 1.5rem; --topbar-h: 3.1rem; --r: 6px;
  --btn: #ffffff; --btn-down: #eef0f3;
  --btn-primary: #2a6fcb; --btn-primary-down: #255fae;
  --bar: #ffffff;
  font-family: var(--font); font-size: 14px; color: var(--ink); color-scheme: light;
  background: #f3f3f2;
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: #f3f3f2; }
h1, h2, h3 { margin: 0; font-weight: 700; }
[hidden] { display: none !important; }

/* Top: the pitch's rounded bar, then the job as a card */
.top { max-width: 1320px; margin: 0 auto; padding: 14px var(--gutter) 0; display: grid; gap: 12px; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; height: 40px; padding: 0 0 0 14px;
  background: var(--bar); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.topbar .links { display: flex; align-self: stretch; align-items: stretch; }
.topbar .links a, .topbar .links button { display: flex; align-items: center; padding: 0 16px; font-size: 13.5px; color: var(--ink);
  text-decoration: none; border: 0; border-radius: 0; background: none; }
.topbar .links a:hover, .topbar .links button:hover { background: #f2f4f7; }
.topbar .links a.here { color: #1d4f91; background: #eaf2fc; font-weight: 700; }
.topbar .levels { display: flex; align-items: center; gap: 0; color: var(--muted); font-size: 13px; padding-left: 8px; }
.topbar .levels a { padding: 0 10px; }
.brand { display: inline-flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 700; color: var(--ink); text-decoration: none; }
@media (max-width: 600px) {
  .top { padding-top: 10px; }
  .topbar { padding-left: 10px; }
  .brand span, .topbar .levels > :not(a) { display: none; }
  .topbar .levels { font-size: 0; padding-left: 0; }
  .topbar .levels a { font-size: 13.5px; padding: 0 9px; }
  .topbar .links a, .topbar .links button { padding: 0 9px; }
}
.brand svg { width: 22px; height: 22px; display: block; }

/* The job: the complaint, loud and clear, and the button to report it done */
.job { display: flex; flex-wrap: wrap; gap: 0.75rem 1.5rem; align-items: center; padding: 0.85rem var(--gutter);
  color: var(--ink); background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
.job-text { flex: 1 1 22rem; min-width: 0; }
/* Pinned under the top bar where the screen has room for it; on phones it scrolls away. */
@media (min-width: 961px) and (min-height: 700px) { .job { position: sticky; top: 8px; z-index: 15; box-shadow: 0 2px 10px rgb(0 0 0 / 0.06); } }
.job-label { font-size: 12px; color: var(--muted); }
.complaint { font-size: clamp(1.1rem, 1rem + 0.8vw, 1.5rem); font-weight: 700; line-height: 1.3; margin: 0.1rem 0 0; }

/* Layout: picture and output on the left; status, moves and controls on the right.
   One column on narrow screens: status first, then the picture, then the controls. */
.layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(270px, 360px); grid-template-rows: auto 1fr;
  grid-template-areas: "view info" "view controls"; gap: 1.25rem 1.5rem; align-items: start;
  max-width: 1320px; margin: 0 auto; padding: 12px var(--gutter) 2rem; }
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
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.1rem; }
.panel + .panel { margin-top: 1rem; }
.panel h2 { font-size: 13px; color: var(--muted); margin-bottom: 0.65rem; }
.panel h2.sub { margin-top: 1rem; padding-top: 0.9rem; border-top: 1px solid #e3e3e3; }

/* Buttons: flat, blue for the main action */
button { display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; font: 13px/1.2 var(--font); color: #111;
  cursor: pointer; padding: 0.5rem 1.1rem; border: 1px solid var(--line-strong); border-radius: 7px; background: var(--btn); }
button:hover:not(:disabled) { background: #f4f5f7; }
button:active:not(:disabled) { background: var(--btn-down); }
button:focus-visible { outline: 3px solid var(--select); outline-offset: 1px; }
button:disabled { opacity: 0.5; cursor: default; }
.primary, .primary:hover:not(:disabled) { background: var(--btn-primary); border-color: #255fae; color: #fff; }
.primary:active:not(:disabled) { background: var(--btn-primary-down); }
.secondary:hover:not(:disabled) { border-color: #6f6f6f; }
.on-dark, .on-dark:hover:not(:disabled) { background: var(--btn-primary); border-color: #255fae; color: #fff; font-weight: 700; font-size: 14px;
  padding: 0.65rem 1.3rem; white-space: nowrap; }
button.link, button.plain, .close { background: none; border: 0; border-radius: 0; padding: 0.15rem 0.25rem; }
button.link { color: #2a5ea3; font-size: 12px; }
button.link:hover { text-decoration: underline; }

/* Move: segmented controls, the current room and view selected in light blue */
.segments, .choice { display: flex; }
.segments { margin-bottom: 0.75rem; }
.segments button, .choice button { border-radius: 0; margin-left: -1px; }
.segments button:first-child, .choice button:first-child { border-radius: 5px 0 0 5px; margin-left: 0; }
.segments button:last-child, .choice button:last-child { border-radius: 0 5px 5px 0; }
.segments button { flex: 1 1 0; min-width: 0; flex-direction: column; gap: 0.1rem; font-size: 13px; font-weight: 700;
  line-height: 1.2; padding: 0.6rem 0.4rem 0.55rem; text-align: center; }
.segments button small { font-size: 11px; font-weight: 400; color: var(--muted); }
.segments button.here, .choice button.on, .segments button.here:hover, .choice button.on:hover { position: relative; z-index: 1;
  background: #eaf2fc; border-color: #9cc0ec; color: #1d4f91; cursor: default; opacity: 1; }
.segments button.here small { color: #3f6aa5; }
.choice button { padding: 0.45rem 0.8rem; }
.choice button.on { cursor: pointer; }
.row { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; }
.note { color: var(--muted); font-size: 12px; margin: 0 0 0.8rem; }
select { font: 13px var(--font); padding: 0.4rem 0.5rem; border: 1px solid var(--line-strong); border-radius: 5px;
  background: var(--btn); color: var(--ink); }
select:focus-visible, input:focus-visible { outline: 3px solid var(--select); outline-offset: 1px; }

/* Status: an inset grouped list, items stacked top to bottom */
.infobox { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; font-size: 13px; color: var(--muted); }
.infobox > div { display: grid; grid-template-columns: 6.5rem 1fr; align-items: center; gap: 0.6rem; padding: 0.5rem 0.9rem; }
.infobox > div + div { border-top: 1px solid #e3e3e3; }
.infobox b { color: var(--ink); font-weight: 700; }
.infobox .val { display: flex; align-items: center; gap: 0.6rem; min-width: 0; }
.meter { flex: 1; max-width: 140px; height: 8px; border-radius: 4px; background: #e8e9eb; overflow: hidden; }
.meter > span { height: 100%; width: 0; background: var(--graphite); }
.meter.damage > span { background: var(--danger); }
@media (max-width: 960px) {
  .infobox { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); }
  .infobox > div { border-bottom: 1px solid #e3e3e3; }
  .infobox > div + div { border-top: 0; }
}

/* The picture: a thin frame (drawn with a shadow, so the clickable tags stay aligned) */
#stage { position: relative; width: 100%; aspect-ratio: 4 / 3; background: #0b0d10; border-radius: 6px; overflow: hidden;
  box-shadow: 0 0 0 1px var(--line); }
#view { width: 100%; height: 100%; display: block; }
.hot { position: absolute; padding: 0; outline: 2px solid transparent; cursor: pointer; }
.hot:hover, .hot:focus-visible { outline: 2px solid var(--select); outline-offset: 0; background: rgb(127 178 239 / 0.18); }
/* After inspect the picture is a close-up; this returns to the whole view (look, which takes no time). */
.back { position: absolute; z-index: 4; right: 10px; bottom: 10px; font-weight: 700; }
.menu { position: absolute; z-index: 5; width: min(260px, calc(100% - 16px)); background: var(--surface); border: 1px solid var(--line-strong);
  border-radius: 8px; overflow: hidden; box-shadow: 0 8px 24px rgb(0 0 0 / 0.18); }
.menu .titlebar { padding: 0.4rem 0.75rem; }
.menu .item { display: flex; justify-content: space-between; gap: 1rem; width: 100%; padding: 0.5rem 0.75rem; text-align: left;
  border-top: 1px solid #e3e3e3; font-size: 13px; }
.menu .item:hover, .menu .item:focus-visible { background: var(--btn-primary); color: #fff; outline: none; }
.menu .item span:last-child { color: var(--muted); font-size: 12px; white-space: nowrap; }
.menu .item:hover span:last-child, .menu .item:focus-visible span:last-child { color: #e6eef8; }

/* Output: plain monospace output, the command line at its foot, history in the corner.
   A click anywhere in it puts the cursor on the command line. */
.console { margin-top: 1rem; background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  font: 12.5px/1.55 var(--mono); cursor: text; }
.console:focus-within { border-color: var(--select); }
.console-head { display: flex; justify-content: flex-end; padding: 0.2rem 0.4rem 0; font-family: var(--font); }
#transcript { max-height: 320px; overflow: auto; padding: 0 1rem; border-bottom: 1px dashed var(--line); }
#transcript pre, #latest { white-space: pre-wrap; word-break: break-word; margin: 0 0 0.8rem; font: inherit; }
#transcript .cmd, .prompt span { color: var(--graphite-dark); font-weight: 700; }
#latest { padding: 0.1rem 1rem 0; margin: 0; }
.prompt { display: flex; gap: 0.6rem; align-items: center; padding: 0.35rem 1rem 0.7rem; }
.prompt input { flex: 1; min-width: 0; font: inherit; border: 0; padding: 0.15rem 0; background: transparent; color: var(--ink); }
.prompt input:focus, .prompt input:focus-visible { outline: none; }
@media (max-width: 600px) { .console { font-size: 12px; } #latest, #transcript, .prompt { padding-left: 0.6rem; padding-right: 0.6rem; } }

/* Result: the score large, every other fact in a table */
.result .big { display: flex; align-items: baseline; gap: 0.6rem; margin-bottom: 0.25rem; }
.result .score { font-size: 4rem; font-weight: 700; line-height: 1; color: var(--ink); }
.result .of { color: var(--muted); font-size: 14px; }
.result .verdict { margin: 0 0 1rem; font-weight: 700; }
table.facts { width: 100%; border-collapse: collapse; font-size: 13px; }
table.facts th, table.facts td { text-align: left; vertical-align: top; padding: 0.4rem 0.5rem; border-top: 1px solid #e3e3e3; overflow-wrap: anywhere; }
table.facts th { width: 45%; color: var(--muted); font-weight: 400; }
table.facts tr.group th { color: var(--ink); font-weight: 700; padding-top: 0.9rem; }
.pass { color: var(--ok); font-weight: 700; } .fail { color: var(--danger); font-weight: 700; }
details.raw { margin-top: 1rem; }
details.raw summary { cursor: pointer; color: #2a5ea3; }
details.raw pre { max-height: 360px; overflow: auto; background: #f4f4f4; border: 1px solid var(--line); border-radius: 4px; padding: 0.75rem;
  font: 12px/1.45 var(--mono); }

/* Dialogs: a sheet with a light title bar */
.backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; padding: 1rem; background: rgb(0 0 0 / 0.3); }
.modal { width: 100%; max-width: 640px; max-height: calc(100dvh - 2rem); display: flex; flex-direction: column; min-width: 0;
  background: var(--surface); border: 1px solid var(--line-strong); border-radius: 10px; overflow: hidden; box-shadow: 0 16px 48px rgb(0 0 0 / 0.2); }
.modal.wide { max-width: 860px; }
.titlebar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.45rem 0.6rem 0.45rem 1.1rem;
  background: #f6f7f8; border-bottom: 1px solid var(--line); }
.titlebar h2 { font-size: 13px; color: #222; }
.close { font-size: 1.3rem; line-height: 1; color: var(--muted); padding: 0.1rem 0.4rem; }
.modal-body { padding: 1.1rem 1.4rem 1.4rem; overflow-y: auto; display: grid; grid-auto-rows: max-content; gap: 0.85rem; min-width: 0; }
.modal-body p { margin: 0; }
.modal-body h3 { font-size: 13px; }
@media (max-width: 600px) { .backdrop { padding: 0.5rem; } .modal-body { padding: 1rem; } }
.actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.75rem; padding-top: 0.5rem; }
label.check { display: flex; gap: 0.75rem; align-items: flex-start; padding: 0.55rem 0.75rem; border: 1px solid var(--line); border-radius: var(--r); cursor: pointer; }
label.check:hover { border-color: var(--line-strong); }
label.check input { margin-top: 0.2rem; accent-color: var(--graphite-dark); width: 1.05rem; height: 1.05rem; flex: none; }
label.check b { display: block; }
label.check span { color: var(--muted); font-size: 12.5px; }
.faults { display: grid; gap: 0.45rem; }
.callout { display: grid; gap: 0.55rem; padding: 0.75rem 0.9rem; background: #f4f4f4; border: 1px solid var(--line); border-radius: var(--r); }
.callout code, .rules code { font-family: var(--mono); font-size: 0.92em; overflow-wrap: anywhere; }
.rules h1 { font-size: 15px; margin: 0.4rem 0; } .rules h2 { font-size: 13px; margin: 1rem 0 0.35rem; }
.rules ul { margin: 0.25rem 0; padding-left: 1.2rem; } .rules li { margin: 0.2rem 0; } .rules p { margin: 0.4rem 0; }
.rules pre, pre.cmds { background: #f4f4f4; border: 1px solid var(--line); border-radius: 4px; padding: 0.6rem 0.75rem; overflow: auto; font: 12px/1.5 var(--mono); max-width: 100%; }
.help-ui { margin: 0; padding-left: 1.2rem; } .help-ui li { margin: 0.25rem 0; }
</style></head><body>
<div class="top">
<header class="topbar"><a class="brand" href="https://plumberbench.org/">{ICON}<span>PlumberBench</span></a>
  <nav class="links" aria-label="Game"><span class="levels" id="levels" hidden>Level
    <a href="?level=1">1</a><a href="?level=2">2</a><a href="?level=3">3</a><a href="?level=4">4</a><a href="?level=5">5</a></span>
    <a href="?new=1" id="newhouse" hidden>New house</a><button id="help">Help</button></nav></header>

<section class="job" aria-live="polite">
  <div class="job-text">
    <div class="job-label" id="joblabel">The job</div>
    <p class="complaint" id="complaint"></p>
  </div>
  <button class="on-dark" id="finish">Report job finished</button>
</section>
</div>

<main class="layout">
  <section class="view-col">
    <div id="stage"><img id="view" alt="The current view"><div id="hots"></div>
      <button class="secondary back" id="back" hidden>Back to the whole view</button>
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
    <div><span>Free actions</span><b id="st-free"></b></div>
    <div><span>Bucket</span><b id="st-bucket"></b></div>
    <div><span>Where</span><b id="st-where"></b></div>
  </section>
  <aside class="controls">
    <section class="panel result" id="result" hidden></section>
    <section class="panel" id="controlpanel"><h2>Move</h2>
      <div class="segments" id="rooms"></div>
      <div class="segments" id="views"></div>
      <h2 class="sub">Water and time</h2>
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
      <li>Inspect shows a close-up of the part. Back to the whole view, on the picture, returns to the full view and takes no time.</li>
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
let room = "", view = "", over = false, side = "cold", result = null, zoomed = false;
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
  const free = /free actions (\d+)\/(\d+)/.exec(text);
  if (free) $("st-free").textContent = free[1] + " of " + free[2];
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
  $("views").replaceChildren(...(S.views[room] || []).map(([k, label]) => k === view && zoomed
    ? segment(label, "Back to the whole view", "look " + k, false)
    : segment(label, k === view ? "You are looking here" : units(S.cost.look), "look " + k, k === view)));
  $("back").hidden = !zoomed || over;
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
$("back").onclick = () => send("look " + view);
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

const isInspect = line => /^\s*inspect\s/i.test(line || "");
function apply(p, line, pictureLine = line) {
  if (line !== undefined) record(line, p.text);
  $("latest").textContent = p.text;
  setComplaint(p.text);
  if (p.image) zoomed = isInspect(pictureLine);  // a successful inspect shows a close-up
  parseStatus(p.text);
  if (p.image) drawPicture(p);
  if (p.result && !result) showResult(p.result);
  closeMenu();
}

async function send(line, quiet) {
  if (!line.trim()) return;
  if (!quiet) { typed.push(line); tpos = typed.length; }
  const r = await fetch("command", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({line})});
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
  free_actions: "Actions that took no time", free_action_limit_hit: "Hit the free-action limit",
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
  $("result").hidden = false; $("controlpanel").hidden = true;
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
fetch("history" + location.search).then(r => r.json()).then(h => {
  if (h.online) {  /* online play: pick a level or a fresh house; locally there is one house */
    $("levels").hidden = $("newhouse").hidden = false;
    $("newhouse").href = "?level=" + h.level + "&new=1";
    $("levels").querySelectorAll("a").forEach(a => a.classList.toggle("here", a.textContent === String(h.level)));
    if (/[?&]new=1/.test(location.search)) history.replaceState(null, "", "?level=" + h.level);
  }
  h.log.forEach(([line, text]) => { record(line, text); setComplaint(text); });
  const shown = [...h.log].reverse().find(([, text]) => text === h.current.text);
  apply(h.current, undefined, shown && shown[0]);
});
</script></body></html>
""".replace("__STATIC__", json.dumps(STATIC)).replace("{ICON}", icon("pbicon"))


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
