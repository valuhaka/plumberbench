"""The browser page at phone, tablet, laptop and desktop sizes.

Needs Playwright and a Chromium or Chrome; skipped otherwise. Set
PB_LAYOUT_SHOTS=<dir> to also save a screenshot per size.
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from live import SRC, free_port  # noqa: E402

SIZES = [(360, 740), (414, 896), (768, 1024), (1024, 768), (1280, 800), (1440, 900), (1920, 1080)]
BLOCKS = [".topbar", ".job", "#stage", ".console", ".infobox", "#movepanel", "#waterpanel"]


@pytest.fixture(scope="module")
def page_url(tmp_path_factory):
    port = free_port()
    out = tmp_path_factory.mktemp("play")
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.Popen([sys.executable, "-m", "plumberbench.play", "--seed", "7", "--level", "3", "--web",
                             "--no-browser", "--port", str(port), "--out", str(out)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    yield url
    proc.kill()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            exe = next((shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser") if shutil.which(n)), None)
            if not exe:
                pytest.skip("no Chromium or Chrome for Playwright")
            b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        yield b
        b.close()


def rect(page, selector):
    return page.eval_on_selector(selector, "e => { const r = e.getBoundingClientRect(); "
                                           "return [r.left, r.top, r.right, r.bottom]; }")


def overlaps(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


@pytest.mark.parametrize("width,height", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_page_fits_every_screen(browser, page_url, width, height):
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(page_url)
    page.wait_for_selector(".hot", state="attached")
    page.wait_for_timeout(300)
    shots = os.environ.get("PB_LAYOUT_SHOTS")
    if shots:
        page.screenshot(path=str(Path(shots) / f"page_{width}x{height}.png"), full_page=True)

    assert not errors
    assert page.evaluate("document.documentElement.scrollWidth") <= width, "the page scrolls sideways"
    rects = {s: rect(page, s) for s in BLOCKS}
    for s, r in rects.items():
        assert r[0] >= -0.5 and r[2] <= width + 0.5, f"{s} sticks out of the window: {r}"
    # Main blocks never sit on top of each other.
    for a in ("#stage", ".console", ".infobox", "#movepanel", "#waterpanel"):
        for b in ("#stage", ".console", ".infobox", "#movepanel", "#waterpanel"):
            if a < b:
                assert not overlaps(rects[a], rects[b]), f"{a} overlaps {b}"
    # No button label is cut off.
    clipped = page.evaluate("""[...document.querySelectorAll('button')].filter(b => b.offsetParent &&
        b.scrollWidth > b.clientWidth + 1).map(b => b.textContent)""")
    assert clipped == []
    if width > 960:
        assert rects[".infobox"][0] >= rects["#stage"][2], "status sits right of the picture"
        if height >= 800:
            assert rects[".console"][1] < height, "the output starts within the first screen"
    else:
        assert rects[".infobox"][3] <= rects["#stage"][1], "status sits above the picture"

    # A tag's menu opens inside the picture.
    page.locator(".hot").first.click()
    menu, stage = rect(page, "#menu"), rect(page, "#stage")
    assert stage[0] - 0.5 <= menu[0] and menu[2] <= stage[2] + 0.5 and menu[3] <= stage[3] + 0.5
    page.keyboard.press("Escape")
    # Dialogs fit the window.
    page.click("#finish")
    dialog = rect(page, "#finishdlg .modal")
    assert dialog[0] >= 0 and dialog[2] <= width
    page.close()


def test_a_click_anywhere_in_the_output_reaches_the_command_line(browser, page_url):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(page_url)
    page.wait_for_selector(".hot", state="attached")
    page.click("#latest")
    assert page.evaluate("document.activeElement.id") == "cmd"
    page.close()
