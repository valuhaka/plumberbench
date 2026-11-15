"""PlumberBench online: the play page for many visitors at once, each in a house of their own.

    python -m plumberbench.online --port 8080

Runs in a container behind the website, at plumberbench.org/play/ (Dockerfile, worker/).
The page and every reply are the local play page's (web.py, play.handle), so a visitor
gets exactly what an agent gets. A session cookie holds the visitor's house: a random
seed at level 1 in pictures-only mode, or ?level=N&seed=N to choose, and ?new=1 for a
fresh one. Reloading the page
continues the house until the job is over, then opens a new one. A house closes after
30 minutes without a move; at most MAX_HOUSES are open, and a new visitor closes the one
idle longest. Nothing is written to disk.
"""
from __future__ import annotations

import argparse
import random
import secrets
import threading
import time
from dataclasses import dataclass, field

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from .env import Episode
from .generate import LEVELS
from .play import Reply, handle
from .web import PAGE, payload

COOKIE = "pb_house"
IDLE = 30 * 60
MAX_HOUSES = 64
MAX_LINE = 200
CLOSED = "This house closed after 30 minutes without a move. Reload the page for a new one."


@dataclass
class House:
    ep: Episode
    current: Reply
    log: list
    lock: threading.Lock = field(default_factory=threading.Lock)
    seen: float = field(default_factory=time.monotonic)


class Houses:
    def __init__(self, render: bool = True, max_houses: int = MAX_HOUSES, idle: float = IDLE):
        self.render, self.max_houses, self.idle = render, max_houses, idle
        self.houses: dict[str, House] = {}
        self.lock = threading.Lock()

    def get(self, sid: str | None) -> House | None:
        with self.lock:
            self._close_idle()
            house = self.houses.get(sid or "")
            if house:
                house.seen = time.monotonic()
            return house

    def open(self, level: int, seed: int) -> tuple[str, House]:
        ep = Episode(seed, level, facts=False, render=self.render)
        first = handle(ep, "briefing")
        house = House(ep, first, [("briefing", first.text)])
        sid = secrets.token_urlsafe(18)
        with self.lock:
            self._close_idle()
            while len(self.houses) >= self.max_houses:
                del self.houses[min(self.houses, key=lambda k: self.houses[k].seen)]
            self.houses[sid] = house
        return sid, house

    def _close_idle(self) -> None:
        now = time.monotonic()
        for sid in [k for k, h in self.houses.items() if now - h.seen > self.idle]:
            del self.houses[sid]


def _choice(request: Request) -> tuple[int | None, int | None]:
    """The level and seed asked for in the page's query, if any and valid."""
    def number(name, lo, hi):
        try:
            v = int(request.query_params[name])
        except (KeyError, ValueError):
            return None
        return v if lo <= v <= hi else None
    return number("level", min(LEVELS), max(LEVELS)), number("seed", 0, 10**9)


def make_app(houses: Houses) -> Starlette:
    # Plain `def` handlers: Starlette runs them in a thread pool, so one house's render
    # does not hold up the others' requests.
    def page(_: Request):
        return HTMLResponse(PAGE)

    def history(request: Request):
        level, seed = _choice(request)
        sid = request.cookies.get(COOKIE)
        house = houses.get(sid)
        state = house.ep.state if house else None
        fresh = request.query_params.get("new") == "1"
        if (state is None or state.done or fresh or (level is not None and level != state.level)
                or (seed is not None and seed != state.seed)):
            sid, house = houses.open(level or 1, random.randrange(10**6) if seed is None else seed)
        with house.lock:
            body = {"log": house.log, "current": payload(house.current), "online": True,
                    "level": house.ep.state.level}
        response = JSONResponse(body)
        response.set_cookie(COOKIE, sid, max_age=IDLE, httponly=True, samesite="lax", path="/")
        return response

    async def command(request: Request):
        try:
            line = str((await request.json())["line"])[:MAX_LINE]
        except (ValueError, KeyError, TypeError):
            return JSONResponse(payload(Reply("Send {\"line\": \"<command>\"}.")), status_code=400)
        house = houses.get(request.cookies.get(COOKIE))
        if house is None:
            return JSONResponse(payload(Reply(CLOSED)), status_code=410)
        return JSONResponse(await _run(house, line))

    def health(_: Request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/", page), Route("/history", history), Route("/health", health),
                             Route("/command", command, methods=["POST"])])


async def _run(house: House, line: str) -> dict:
    from starlette.concurrency import run_in_threadpool

    def step():
        with house.lock:
            reply = handle(house.ep, line)
            house.log.append((line, reply.text))
            if reply.image:
                house.current = reply
            return payload(reply)
    return await run_in_threadpool(step)


def main() -> int:
    import uvicorn
    ap = argparse.ArgumentParser(description="Serve the play page to many visitors, a house each.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--max-houses", type=int, default=MAX_HOUSES)
    a = ap.parse_args()
    uvicorn.run(make_app(Houses(max_houses=a.max_houses)), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
