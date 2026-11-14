"""Browser play page: a local front-end over the same episode as the terminal.

    python -m plumberbench.play --seed 3 --level 2 --web

Rules that keep it honest (tests/test_views.py enforces them):

  - Every action is a typed command line sent to `play.handle`, the same
    function the terminal uses. Buttons and menus only write those lines.
  - A response carries `text`, `image` and `hotspots`, nothing else. Text and
    image are exactly what the agent gets for that call. Hotspots are the boxes
    of the tag labels already drawn on the picture.
  - The page itself is static: the same bytes for every house and every state.
    Menus depend only on a part's kind (its tag letter), never on its state,
    and costs come from the rules table, as stated in the instruction.

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
from .world import COST, DIAGNOSES

ROUTES = ("/", "/history", "/command")
PAYLOAD_KEYS = ("text", "image", "hotspots")

# What a click on a tag offers, by the tag's letter: (label, command template, cost).
MENUS = {
    "V": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Turn to open", "set_valve {tag} open", COST["set_valve"]),
          ("Turn to half", "set_valve {tag} half", COST["set_valve"]),
          ("Turn to closed", "set_valve {tag} closed", COST["set_valve"])],
    "J": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Put bucket under", "place_bucket {tag}", COST["place_bucket"]),
          ("Tighten", "repair {tag} tighten", COST["repair"]),
          ("Undo joint", "open_joint {tag}", COST["open_joint"]),
          ("Refit with new washer", "close_joint {tag}", COST["close_joint"])],
    "T": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Put bucket under", "place_bucket {tag}", COST["place_bucket"]),
          ("Remove trap", "open_joint {tag}", COST["open_joint"]),
          ("Clear", "repair {tag} clear", COST["repair"]),
          ("Refit with new washer", "close_joint {tag}", COST["close_joint"])],
    "C": [("Inspect (tap the pipe)", "inspect {tag}", COST["inspect"]),
          ("Put bucket under", "place_bucket {tag}", COST["place_bucket"]),
          ("Take out plug", "open_joint {tag}", COST["open_joint"]),
          ("Clear", "repair {tag} clear", COST["repair"]),
          ("Refit with new washer", "close_joint {tag}", COST["close_joint"])],
    "A": [("Inspect", "inspect {tag}", COST["inspect"]),
          ("Clear", "repair {tag} clear", COST["repair"])],
}
VIEWS = {"kitchen": ["counter", "under_sink"], "bathroom": ["counter", "under_sink"], "utility": ["wall"]}
STATIC = {"menus": MENUS, "views": VIEWS, "diagnoses": list(DIAGNOSES), "go_cost": COST["go"]}


def payload(reply: Reply) -> dict:
    return {
        "text": reply.text,
        "image": base64.b64encode(reply.image).decode() if reply.image else None,
        "hotspots": reply.hotspots,
    }


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>PlumberBench</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#14161b; --panel:#1d2027; --line:#2c3039; --text:#e9eaee; --dim:#9aa0ab;
          --accent:#ffcf4a; --bad:#ff6b6b; --good:#6bd68a; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 system-ui, sans-serif; }
  header { display:flex; gap:16px; align-items:baseline; padding:10px 18px; border-bottom:1px solid var(--line); }
  header h1 { font-size:17px; margin:0; }
  header span { color:var(--dim); font-size:13px; }
  main { display:grid; grid-template-columns:minmax(0,800px) minmax(300px,1fr); gap:18px; padding:16px 18px; }
  #stage { position:relative; width:100%; aspect-ratio:4/3; background:#000; border-radius:6px; overflow:hidden; }
  #view { width:100%; height:100%; display:block; }
  .hot { position:absolute; background:transparent; border:2px solid transparent; border-radius:6px;
         cursor:pointer; padding:0; }
  .hot:hover:not(:disabled), .hot:focus-visible { background:transparent; border-color:var(--accent); outline:none; }
  #menu { position:absolute; z-index:5; background:var(--panel); border:1px solid var(--line); border-radius:8px;
          padding:6px; min-width:210px; box-shadow:0 8px 24px rgba(0,0,0,.5); display:none; }
  #menu h3 { margin:2px 6px 6px; font-size:13px; color:var(--dim); font-weight:600; }
  #menu button { display:flex; justify-content:space-between; width:100%; text-align:left; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin-bottom:12px; }
  .panel h2 { font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:var(--dim); margin:0 0 8px; }
  button { background:#2a2e37; color:var(--text); border:1px solid #363b46; border-radius:6px; padding:6px 10px;
           font:inherit; font-size:14px; cursor:pointer; }
  button:hover:not(:disabled) { background:#343946; }
  button:disabled { opacity:.45; cursor:default; }
  button.on { border-color:var(--accent); color:var(--accent); }
  .cost { color:var(--dim); font-size:12px; margin-left:12px; }
  .row { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-bottom:6px; }
  .bar { height:8px; background:#2a2e37; border-radius:4px; overflow:hidden; flex:1; }
  .bar > div { height:100%; background:var(--accent); width:0; }
  .bar.dmg > div { background:var(--bad); }
  .stat { display:grid; grid-template-columns:70px 1fr 64px; gap:8px; align-items:center; font-size:13px; margin-bottom:6px; }
  .stat b { text-align:right; font-weight:600; }
  select, input[type=text] { background:#2a2e37; color:var(--text); border:1px solid #363b46; border-radius:6px;
           padding:6px 8px; font:inherit; font-size:14px; }
  #cmd { width:100%; font-family:ui-monospace, monospace; }
  #log { max-height:340px; overflow:auto; }
  #log pre { white-space:pre-wrap; word-break:break-word; margin:0 0 8px; padding:8px; background:#121419;
             border-radius:6px; font:12.5px/1.45 ui-monospace, monospace; }
  #log pre.cmd { background:none; padding:0 0 2px; color:var(--accent); margin:0; }
  #latest { white-space:pre-wrap; word-break:break-word; font:13px/1.5 ui-monospace, monospace; margin:10px 0 0; }
  label.dx { display:flex; gap:6px; align-items:center; font-size:13px; margin:3px 0; }
  .over { color:var(--good); font-weight:600; }
</style></head><body>
<header><h1>PlumberBench</h1><span>Click a tag on the picture for its actions. Every button types a command
into the box below; you can also type commands yourself (try <code>help</code>).</span></header>
<main>
  <section>
    <div id="stage"><img id="view" alt="the current view"><div id="hots"></div><div id="menu" role="menu"></div></div>
    <pre id="latest" aria-live="polite"></pre>
  </section>
  <aside>
    <div class="panel"><h2>Status</h2>
      <div class="stat"><span>Time</span><div class="bar"><div id="timebar"></div></div><b id="time"></b></div>
      <div class="stat"><span>Damage</span><div class="bar dmg"><div id="dmgbar"></div></div><b id="dmg"></b></div>
      <div class="stat"><span>Washers</span><span></span><b id="washers"></b></div>
      <div class="stat"><span>Bucket</span><span id="bucket" style="grid-column: span 2"></span></div>
    </div>
    <div class="panel"><h2>Where</h2>
      <div class="row" id="rooms"></div><div class="row" id="views"></div></div>
    <div class="panel" id="tappanel"><h2>Tap and time</h2>
      <div class="row"><span>Run</span>
        <select id="side"><option>cold</option><option>hot</option><option>both</option></select>
        <span>for</span><select id="tapticks"></select><button id="runtap">Run tap</button></div>
      <div class="row"><span>Wait</span><select id="waitticks"></select><button id="wait">Wait</button></div>
    </div>
    <div class="panel"><h2>Finish</h2><div id="dx"></div>
      <div class="row"><button id="finish">Report the job finished</button><button id="score">Score</button></div></div>
    <div class="panel"><h2>Command</h2><input id="cmd" type="text" autocomplete="off" spellcheck="false"
      placeholder="e.g. inspect J4" aria-label="command"></div>
    <div class="panel"><h2>Log</h2><div id="log"></div></div>
  </aside>
</main>
<script>
const S = __STATIC__;
const $ = id => document.getElementById(id);
let room = "", view = "", over = false;
const history = []; let hpos = 0;

function parseStatus(text) {
  const m = /^STATUS: step (\\d+) \\| time (\\d+)\\/(\\d+) \\| damage (\\d+) \\| (\\w+)\\/(\\w+) \\| (.*?) \\| washers (\\d+)/m.exec(text);
  if (!m) return;
  const [_, step, t, budget, dmg, r, v, bucket, washers] = m;
  $("time").textContent = t + "/" + budget; $("timebar").style.width = (100 * t / budget) + "%";
  $("dmg").textContent = dmg; $("dmgbar").style.width = Math.min(100, 5 * dmg) + "%";
  $("washers").textContent = washers; $("bucket").textContent = bucket;
  room = r; view = v; drawWhere();
}

function drawWhere() {
  $("rooms").replaceChildren(...Object.keys(S.views).map(r => button(
    r + (r === room ? "" : " (" + S.go_cost + ")"), "go " + r, r === room)));
  $("views").replaceChildren(...(S.views[room] || []).map(v => button(
    v.replace("_", " ") + " (0)", "look " + v, v === view)));
  $("tappanel").querySelectorAll("button, select").forEach(e => e.disabled = over);
  $("runtap").disabled = over || !(room in S.views && room !== "utility");
}

function button(label, line, current) {
  const b = document.createElement("button");
  b.textContent = label; b.disabled = over || current; if (current) b.className = "on";
  b.onclick = () => send(line);
  return b;
}

function show(p, line) {
  if (line !== undefined) {
    const c = document.createElement("pre"); c.className = "cmd"; c.textContent = "> " + line;
    const t = document.createElement("pre"); t.textContent = p.text;
    $("log").prepend(c, t);
  }
  $("latest").textContent = p.text;
  if (p.text.includes("The job is over")) over = true;
  parseStatus(p.text);
  if (p.image) {
    $("view").src = "data:image/jpeg;base64," + p.image;
    $("hots").replaceChildren(...p.hotspots.map(h => {
      const b = document.createElement("button");
      b.className = "hot"; b.setAttribute("aria-label", "actions for " + h.tag);
      const [x0, y0, x1, y1] = h.box;
      Object.assign(b.style, {left: (x0 / 8) + "%", top: (y0 / 6) + "%",
        width: ((x1 - x0) / 8) + "%", height: ((y1 - y0) / 6) + "%"});
      b.onclick = e => { e.stopPropagation(); openMenu(h); };
      return b;
    }));
  }
  closeMenu();
  document.querySelectorAll("#finish, #dx input").forEach(e => e.disabled = over);
}

function openMenu(h) {
  if (over) return;
  const m = $("menu"); const items = S.menus[h.tag[0]] || [];
  const head = document.createElement("h3"); head.textContent = h.tag;
  m.replaceChildren(head, ...items.map(([label, tpl, cost]) => {
    const b = document.createElement("button"); b.setAttribute("role", "menuitem");
    const l = document.createElement("span"); l.textContent = label;
    const c = document.createElement("span"); c.className = "cost"; c.textContent = cost ? cost + " time" : "free";
    b.append(l, c); b.onclick = () => send(tpl.replace("{tag}", h.tag)); return b;
  }));
  const [x0, y0, x1, y1] = h.box;
  m.style.left = Math.min(x1 / 8, 70) + "%"; m.style.top = Math.min(y0 / 6, 55) + "%";
  m.style.display = "block"; m.querySelector("button")?.focus();
}
function closeMenu() { $("menu").style.display = "none"; }

async function send(line) {
  if (!line.trim()) return;
  history.push(line); hpos = history.length;
  const r = await fetch("/command", {method: "POST", headers: {"Content-Type": "application/json"},
                                     body: JSON.stringify({line})});
  show(await r.json(), line);
}

$("cmd").addEventListener("keydown", e => {
  if (e.key === "Enter") { send(e.target.value); e.target.value = ""; }
  if (e.key === "ArrowUp" && hpos > 0) { e.target.value = history[--hpos]; e.preventDefault(); }
  if (e.key === "ArrowDown") { hpos = Math.min(history.length, hpos + 1); e.target.value = history[hpos] || ""; }
});
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenu(); });
document.addEventListener("click", e => { if (!$("menu").contains(e.target)) closeMenu(); });

for (let i = 1; i <= 5; i++) $("tapticks").add(new Option(i + (i > 1 ? " ticks" : " tick"), i));
for (let i = 1; i <= 10; i++) $("waitticks").add(new Option(i + (i > 1 ? " ticks" : " tick"), i));
$("runtap").onclick = () => send(`run_tap ${$("side").value} ${$("tapticks").value}`);
$("wait").onclick = () => send(`wait ${$("waitticks").value}`);
$("dx").replaceChildren(...S.diagnoses.map(d => {
  const l = document.createElement("label"); l.className = "dx";
  const c = document.createElement("input"); c.type = "checkbox"; c.value = d;
  l.append(c, d.replace(/_/g, " ")); return l;
}));
$("finish").onclick = () => {
  const picked = [...document.querySelectorAll("#dx input:checked")].map(c => c.value);
  if (confirm("Finish the job with diagnosis: " + (picked.join(", ") || "(none)") + "?"))
    send("finish " + picked.join(" "));
};
$("score").onclick = () => send("score");

fetch("/history").then(r => r.json()).then(h => {
  h.log.forEach(([line, text]) => show({text, image: null, hotspots: []}, line));
  show(h.current);
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
