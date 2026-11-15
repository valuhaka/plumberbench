"""The online play server: a house per visitor, the same page and replies as local play, and it
works under a path prefix (the Worker serves it at /play/)."""
import time

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from plumberbench import online
from plumberbench.env import Episode
from plumberbench.play import handle
from plumberbench.web import payload


def client(**kw):
    return TestClient(online.make_app(online.Houses(render=False, **kw)))


def test_each_visitor_gets_a_house_of_their_own():
    a, b = client(), None
    first = a.get("/history?level=2&seed=5").json()
    assert first["log"][0][0] == "briefing"
    reply = a.post("/command", json={"line": "look under_sink"}).json()
    assert "under_sink" in reply["text"]
    assert len(a.get("/history").json()["log"]) == 2  # the same house again, by cookie

    b = TestClient(a.app)
    assert len(b.get("/history?level=2&seed=5").json()["log"]) == 1  # a fresh house


def test_replies_are_the_local_ones():
    """What a visitor gets is exactly what local play (and so the agent) gets."""
    c = client()
    c.get("/history?level=3&seed=11")
    ep = Episode(11, 3, facts=False, render=False)
    handle(ep, "briefing")
    for line in ("go bathroom", "run_tap both 2", "look under_sink"):
        assert c.post("/command", json={"line": line}).json() == payload(handle(ep, line))


def test_asking_for_another_house_opens_it():
    c = client()
    c.get("/history?level=1&seed=1")
    c.post("/command", json={"line": "go bathroom"})
    log = c.get("/history?level=4&seed=2").json()["log"]
    assert len(log) == 1 and "time 0/65" in log[0][1]


def test_new_opens_a_fresh_house_and_the_page_learns_the_level():
    c = client()
    first = c.get("/history?level=2&seed=8").json()
    assert first["online"] and first["level"] == 2
    c.post("/command", json={"line": "go bathroom"})
    again = c.get("/history?level=2&new=1").json()
    assert len(again["log"]) == 1 and again["level"] == 2


def test_a_finished_house_gives_way_to_a_new_one():
    c = client()
    c.get("/history?level=1&seed=6")
    assert c.post("/command", json={"line": "finish"}).json()["result"]
    assert len(c.get("/history").json()["log"]) == 1


def test_a_move_without_a_house_says_so():
    r = client().post("/command", json={"line": "look counter"})
    assert r.status_code == 410 and "Reload the page" in r.json()["text"]


def test_idle_houses_close_and_the_count_is_capped():
    houses = online.Houses(render=False, max_houses=2, idle=0.05)
    first, _ = houses.open(1, 1)
    houses.open(1, 2)
    houses.open(1, 3)
    assert len(houses.houses) == 2 and first not in houses.houses
    time.sleep(0.1)
    assert houses.get("anything") is None and not houses.houses


def test_the_page_works_under_a_prefix():
    """The Worker serves the server at /play/; the page's requests must stay under it."""
    app = Starlette(routes=[Mount("/play", app=online.make_app(online.Houses(render=False)))])
    c = TestClient(app)
    page = c.get("/play/").text
    assert 'fetch("command"' in page and 'fetch("history" + location.search)' in page
    assert c.get("/play/history?level=1&seed=4").json()["log"]
    assert c.post("/play/command", json={"line": "look counter"}).status_code == 200


def test_the_page_plays_in_a_browser_under_the_prefix(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    import threading

    import uvicorn
    from live import free_port
    from test_page_layout import _launch

    app = Starlette(routes=[Mount("/play", app=online.make_app(online.Houses()))])
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        with sync_api.sync_playwright() as p:
            browser = _launch(p)
            if browser is None:
                pytest.skip("no browser to drive (Playwright's Chromium, Chrome or Edge)")
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/play/?level=1&seed=3")
            page.wait_for_function("document.getElementById('complaint').textContent.length > 0")
            page.fill("#cmd", "look under_sink")
            page.press("#cmd", "Enter")
            page.wait_for_function("document.getElementById('latest').textContent.includes('under_sink')")
            browser.close()
    finally:
        server.should_exit = True
