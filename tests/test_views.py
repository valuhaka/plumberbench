"""Information consistency across every way of seeing an episode.

The same commands go through three front-ends: the agent's MCP server, the
terminal (`play`, as a real subprocess) and the browser page (`play --web`).
For every command they must show the same text and the same picture, byte for
byte, and the browser may add nothing the terminal does not have.
"""
import base64
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from live import SRC, start_server
from PIL import Image
from starlette.testclient import TestClient

from plumberbench import play, web
from plumberbench.env import Episode
from plumberbench.solver import Solver

SEED, LEVEL = 7, 3


def as_line(tool: str, args: dict) -> str:
    if tool == "finish":
        return " ".join(["finish", *args["diagnosis"]])
    return " ".join([tool, *(str(args[name]) for name in play.ARGS[tool])])


def tags_of(cid: str) -> str:
    return Episode(SEED, LEVEL, render=False).state.comps[cid].tag


def script() -> list[tuple[str, bool]]:
    """(command line, whether the MCP server can take it) for a whole reference run plus mistakes."""
    ep = Episode(SEED, LEVEL, render=False)
    Solver(lambda tool, args: ep.act(tool, **args).text).run()
    run = [as_line(tool, args) for tool, args in ep.actions]
    assert run[0] == "briefing"
    mistakes = [
        ("inspect Z9", True),                                          # no such part
        (f"set_valve {tags_of('stop.bathroom.cold')} closed", True),   # another room
        (f"repair {tags_of('jtail.kitchen')} tighten", True),          # another view
        ("help", False), ("score", False), ("wait soon", False), ("dance", False),
    ]
    return mistakes + [(line, True) for line in run[1:]] + [("inspect Z9", True), ("score", False)]


def status_step(text: str) -> int | None:
    m = re.match(r"STATUS: step (\d+) ", text)
    return int(m.group(1)) if m else None


# ------------------------------------------------------------- front-ends

def via_web(seed: int, facts: bool, lines: list[str], out: Path):
    ep, first = play.start(seed, LEVEL, facts, True, out)
    client = TestClient(web.make_app(ep, first))
    page_before = client.get("/").content
    replies = [client.get("/history").json()["current"]]
    replies += [client.post("/command", json={"line": line}).json() for line in lines]
    return client, page_before, replies


def via_terminal(facts: bool, lines: list[str], out: Path) -> str:
    cmd = [sys.executable, "-m", "plumberbench.play", "--seed", str(SEED), "--level", str(LEVEL),
           "--out", str(out)] + (["--facts"] if facts else [])
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    done = subprocess.run(cmd, input="\n".join(lines) + "\nquit\n", text=True, capture_output=True,
                          env=env, timeout=120, check=True)
    return done.stdout


def via_mcp(tmp_path, facts: bool, lines: list[str]) -> list[tuple[str, bytes | None]]:
    import asyncio

    from mcp.client.session import ClientSession
    try:
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

    proc, port = start_server(tmp_path, PB_SEED=str(SEED), PB_LEVEL=str(LEVEL),
                              PB_FACTS="1" if facts else "0", PB_RENDER="1")

    async def run():
        out = []
        async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp") as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                for line in ["briefing", *lines]:
                    tool, args = play.parse(line)
                    result = await session.call_tool(tool, args)
                    text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
                    images = [c for c in result.content if getattr(c, "type", "") == "image"]
                    out.append((text, base64.b64decode(images[0].data) if images else None))
        return out

    try:
        return asyncio.run(run())
    finally:
        proc.kill()


# ------------------------------------------------------------------ tests

@pytest.mark.parametrize("facts", [False, True], ids=["pictures only", "with facts"])
def test_mcp_terminal_and_browser_show_the_same_thing(tmp_path, facts):
    steps = script()
    if facts:
        steps = steps[:16]
    lines = [line for line, _ in steps]

    client, page, web_replies = via_web(SEED, facts, lines, tmp_path / "web")
    stdout = via_terminal(facts, lines, tmp_path / "tui")
    mcp_lines = [line for line, ok in steps if ok]
    mcp = via_mcp(tmp_path, facts, mcp_lines)

    # Browser vs MCP: same text and picture for every command the agent could send.
    web_for_mcp = [web_replies[0]] + [r for r, (_, ok) in zip(web_replies[1:], steps) if ok]
    assert len(web_for_mcp) == len(mcp)
    for w, (text, image) in zip(web_for_mcp, mcp):
        assert w["text"] == text
        assert (base64.b64decode(w["image"]) if w["image"] else None) == image

    # Browser vs terminal: every reply printed, in order, and the same frames on disk.
    pos = 0
    for w in web_replies:
        found = stdout.find(w["text"], pos)
        assert found >= 0, w["text"][:120]
        pos = found + len(w["text"])
    frames = {status_step(w["text"]): base64.b64decode(w["image"]) for w in web_replies if w["image"]}
    for step, image in frames.items():
        assert (tmp_path / "tui" / f"{SEED}-{LEVEL}" / f"step_{step:03d}.jpg").read_bytes() == image
    last = [w for w in web_replies if w["image"]][-1]
    assert (tmp_path / "tui" / "current.jpg").read_bytes() == base64.b64decode(last["image"])

    # The browser adds nothing: fixed payload keys, fixed routes, a page that never changes.
    assert all(list(w) == list(web.PAYLOAD_KEYS) for w in web_replies)
    assert {r.path for r in client.app.routes} == set(web.ROUTES)
    assert client.get("/").content == page
    other, other_page, _ = via_web(SEED + 1, not facts, ["look under_sink"], tmp_path / "web2")
    assert other_page == page
    history = client.get("/history").json()
    assert list(history) == ["log", "current"]
    assert [text for _, text in history["log"]] == [w["text"] for w in web_replies]

    # The result: nothing while the job runs; afterwards the same full JSON in both front-ends.
    ended = [i for i, w in enumerate(web_replies) if "The job is over" in w["text"]]
    if not ended:
        assert all(w["result"] is None for w in web_replies)
        return
    first_over = ended[0]
    assert all(w["result"] is None for w in web_replies[:first_over])
    result = web_replies[first_over]["result"]
    assert result["score"] > 0.9 and result["faults"] and all("tag" in f for f in result["faults"])
    assert all(w["result"] == result for w in web_replies[first_over:])
    printed = stdout.split("The job is over. The result:\n", 1)[1]
    assert json.loads(printed[:printed.index("\n}\n") + 2]) == result
    assert stdout.count("The job is over. The result:") == 1


def test_hotspots_only_mark_labels_drawn_on_the_picture(tmp_path):
    """Clickable tags are exactly labels already visible on the picture, for parts listed IN VIEW."""
    lines = [line for line, ok in script() if ok][:30]
    _, _, replies = via_web(SEED, False, lines, tmp_path / "web")
    checked = 0
    for w in replies:
        if not w["image"]:
            assert w["hotspots"] == []
            continue
        in_view = set(re.search(r"^IN VIEW: (.*)$", w["text"], re.M).group(1).split())
        img = Image.open(io.BytesIO(base64.b64decode(w["image"]))).convert("RGB")
        for h in w["hotspots"]:
            assert h["tag"] in in_view
            x0, y0, x1, y1 = h["box"]
            # Inside the label's right padding: the cream label fill, whatever the scene behind it.
            patch = [img.getpixel((x1 - 4, y)) for y in range(y0 + 6, y1 - 6)]
            mean = [sum(p[i] for p in patch) / len(patch) for i in range(3)]
            assert all(abs(m - c) < 30 for m, c in zip(mean, (255, 250, 225))), (h, mean)
            checked += 1
    assert checked > 50


def test_the_page_says_nothing_the_agent_and_the_terminal_are_not_told():
    """Every sentence the page states about the task is in the agent's instruction (the terminal's
    `rules`), and every cost and fault description is in the terminal's `help`."""
    from plumberbench.tasks import instruction_text
    from plumberbench.world import COST, DIAGNOSIS_TEXT

    for facts in (False, True):
        rules = instruction_text(facts)
        for sentence in web.FROM_INSTRUCTION:
            assert sentence in rules, sentence
        for letter, kind in web.KINDS.items():
            assert f"{letter} {kind}" in rules
        for d, text in DIAGNOSIS_TEXT.items():
            assert f"`{d}`: {text}." in rules
    for facts in (False, True):
        assert play.handle(Episode(SEED, LEVEL, facts=facts, render=False), "rules").text == instruction_text(facts)
    ep = Episode(SEED, LEVEL, render=False)
    helptext = play.handle(ep, "help").text
    for d, text in DIAGNOSIS_TEXT.items():
        assert d in helptext and text in helptext
    for tool, cost in COST.items():
        if tool in ("look", "go", "inspect", "set_valve", "place_bucket", "open_joint", "close_joint", "repair"):
            line = next(l for l in helptext.splitlines() if l.strip().startswith(tool))
            assert line.endswith(f"({cost})"), line
    assert web.STATIC["cost"] == {"go": COST["go"], "look": COST["look"]}
    for items in web.MENUS.values():
        for _, template, cost in items:
            assert cost == COST[template.split()[0]]


def test_menus_depend_only_on_the_tag_letter():
    """A click menu offers the same actions whatever the part's state, so it reveals nothing."""
    assert set(web.MENUS) == {"V", "J", "T", "C", "A"}
    for items in web.MENUS.values():
        for _, template, _ in items:
            tool, _ = play.parse(template.replace("{tag}", "X1"))
            assert tool in play.ARGS
    assert json.dumps(web.STATIC) in web.PAGE  # plain data, baked into the static page
