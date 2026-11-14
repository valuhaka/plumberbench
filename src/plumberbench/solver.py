"""Reference solver: a scripted plumber.

It has no access to the simulator. It calls the same tools as the agent and
reads only what comes back: the status line, the action text and the FACTS
list of what the current view shows. This file imports nothing from the rest
of the package, so it can be copied into a Harbor `solution/` folder as is.

Method, in short: stop any running leak first, then test every fixture, fix
what the tests point to, and test again, because one fault can hide another.
"""
from __future__ import annotations

import json
import re
import sys

FIXTURES = ("kitchen", "bathroom")
STATUS = re.compile(r"step (\d+) \| time (\d+)/(\d+) \| damage (\d+) \| (\w+)/(\w+) \|")


class Done(Exception):
    pass


class Seen:
    """One parsed tool response."""

    def __init__(self, text: str, facts: list | None):
        self.text = text
        self.error = "\nERROR:" in text
        self.over = "The job is over" in text
        m = STATUS.search(text)
        self.room, self.view = (m.group(5), m.group(6)) if m else ("", "")
        self.facts = facts or []
        for line in text.splitlines():
            if line.startswith("FACTS "):
                self.facts = json.loads(line[6:])

    def all(self, type_: str, **match) -> list[dict]:
        return [f for f in self.facts if f.get("type") == type_
                and all(f.get(k) == v for k, v in match.items())]

    def one(self, type_: str, **match) -> dict | None:
        found = self.all(type_, **match)
        return found[0] if found else None


class Solver:
    def __init__(self, call, facts_source=None, log=None):
        self.call = call                  # call(tool, args) -> response text
        self.facts_source = facts_source  # used only when responses carry no FACTS
        self.log = log or (lambda *_: None)
        self.room = "kitchen"
        self.diag: set[str] = set()
        self.blocked: dict[str, bool | None] = {}
        self.clean: dict[str, bool] = {}
        self.aerator_checked: set[str] = set()
        self.deferred: set[str] = set()   # leaking joints that need the main shut
        self.pending_main: list[tuple[str, str]] = []
        self.need_utility = False
        self.cleanout_checked = False
        self.utility_visits = 0
        self.bucket = None                # tag the bucket stands under
        self.traps_done: set[str] = set()

    # ---------------------------------------------------------- plumbing

    def do(self, tool: str, **args) -> Seen:
        text = self.call(tool, args)
        facts = None
        if "FACTS " not in text and self.facts_source:
            facts = self.facts_source()
        seen = Seen(text, facts)
        self.log(tool, args, text.splitlines()[1] if "\n" in text else text)
        if seen.over:
            raise Done
        if seen.room:
            self.room = seen.room
        return seen

    def bucket_under(self, tag: str) -> None:
        if self.bucket != tag:
            self.do("place_bucket", tag=tag)
            self.bucket = tag

    def goto(self, room: str) -> None:
        if self.room != room:
            self.do("go", room=room)

    def see(self, view: str) -> Seen:
        return self.do("look", view=view)

    # ------------------------------------------------------------ fixes

    def open_valves(self, seen: Seen) -> bool:
        changed = False
        for v in seen.all("valve"):
            if v["role"] != "spare" and v["handle"] != "open":
                self.do("set_valve", tag=v["tag"], position="open")
                self.diag.add("valve_not_open")
                changed = True
        return changed

    def fix_supply_leak(self, fx: str, joint: dict, under: Seen) -> None:
        tag = joint["tag"]
        self.diag.add("supply_leak")
        self.bucket_under(tag)
        if "loose" in self.do("inspect", tag=tag).text:
            self.do("repair", tag=tag, method="tighten")
            return
        if joint["where"] == "tap_side":
            stop = under.one("valve", role="stop", line=joint["line"])["tag"]
            self.do("set_valve", tag=stop, position="closed")
            self.swap_washer(tag)
            self.do("set_valve", tag=stop, position="open")
        else:
            # Upstream of its stop valve: only the main can take the pressure off.
            self.deferred.add(tag)
            self.pending_main.append((fx, tag))

    def swap_washer(self, tag: str) -> None:
        self.do("open_joint", tag=tag)
        self.do("close_joint", tag=tag)  # refitting puts in a new washer

    def fix_drain_leak(self, joint: dict, level: int) -> None:
        tag = joint["tag"]
        self.diag.add("drain_leak")
        if level > 0:
            self.bucket_under(tag)  # standing water: it drips now and pours out if undone
        if "loose" in self.do("inspect", tag=tag).text:
            self.do("repair", tag=tag, method="tighten")
            return
        self.swap_washer(tag)

    def fix_trap(self, under: Seen) -> bool:
        tag = under.one("trap")["tag"]
        self.bucket_under(tag)
        opened = self.do("open_joint", tag=tag)
        was_blocked = "sludge" in opened.text
        if was_blocked:
            self.do("repair", tag=tag, method="clear")
            self.diag.add("trap_clog")
        self.do("close_joint", tag=tag)
        return was_blocked

    # ----------------------------------------------------------- rooms

    def service(self, fx: str, trap_ok: bool) -> None:
        """Test one fixture and fix whatever can be fixed from its own room."""
        self.goto(fx)
        self.clean[fx] = False
        for _ in range(10):
            level = self.see("counter").one("basin")["level"]
            under = self.see("under_sink")
            if self.open_valves(under):
                continue  # a shut valve can hide a leak further on: look again
            wet = [j for j in under.all("joint", state="closed") if j["wet"]]
            supply = [j for j in wet if j["line"] != "drain" and j["tag"] not in self.deferred]
            if supply:
                self.fix_supply_leak(fx, supply[0], under)
                continue
            drain = [j for j in wet if j["line"] == "drain"]
            if drain:
                self.fix_drain_leak(drain[0], level)
                continue

            if self.blocked.get(fx) is None and level > 0:
                # Standing water. Is it on its way out, or stuck?
                after = self.wait_at_counter(1)
                if after >= level:
                    self.blocked[fx] = True
                else:
                    if after > 0:
                        self.wait_at_counter((after + 1) // 2)
                    continue
            if self.blocked.get(fx):
                if not trap_ok:
                    return
                if fx in self.traps_done or not self.fix_trap(under):
                    self.cleanout_checked = False  # not this trap: look further down
                    self.need_utility = True
                    return
                self.traps_done.add(fx)
                self.blocked[fx] = None
                continue

            self.see("counter")
            ran = self.do("run_tap", side="both", ticks=1)
            tap, after = ran.one("tap"), ran.one("basin")["level"]
            if after > 0:
                self.blocked[fx] = True
                continue
            self.blocked[fx] = False
            under = self.see("under_sink")
            if any(j["wet"] and j["tag"] not in self.deferred for j in under.all("joint", state="closed")):
                continue  # running water showed up a leak: the top of the loop deals with it
            if tap["cold"] == tap["hot"] == "full":
                self.clean[fx] = True
                return
            if "full" not in (tap["cold"], tap["hot"]) and fx not in self.aerator_checked:
                self.aerator_checked.add(fx)
                aerator = self.see("counter").one("aerator")["tag"]
                if "crusted" in self.do("inspect", tag=aerator).text:
                    self.do("repair", tag=aerator, method="clear")
                    self.diag.add("aerator_clog")
                    continue
            self.need_utility = True  # what is left is upstream of this room
            return

    def stop_leaks(self, fx: str) -> None:
        """First pass: deal with leaks that are running right now."""
        self.goto(fx)
        for _ in range(4):
            level = self.see("counter").one("basin")["level"]
            under = self.see("under_sink")
            wet = [j for j in under.all("joint", state="closed")
                   if j["wet"] and j["tag"] not in self.deferred]
            if not wet:
                return
            if wet[0]["line"] == "drain":
                self.fix_drain_leak(wet[0], level)
            else:
                self.fix_supply_leak(fx, wet[0], under)

    def wait_at_counter(self, ticks: int) -> int:
        self.see("counter")
        return self.do("wait", ticks=ticks).one("basin")["level"]

    def utility(self, cleanout: bool) -> bool:
        """Do everything that needs the utility room. Returns True if anything changed."""
        self.utility_visits += 1
        changed = False
        if self.pending_main:
            self.goto("utility")
            wall = self.see("wall")
            changed |= self.open_valves(wall)
            main = wall.one("valve", role="main")["tag"]
            self.do("set_valve", tag=main, position="closed")
            for fx, tag in self.pending_main:
                self.goto(fx)
                self.swap_washer(tag)
                self.deferred.discard(tag)
            self.pending_main = []
            self.goto("utility")
            self.do("set_valve", tag=main, position="open")
            changed = True
        self.goto("utility")
        wall = self.see("wall")
        changed |= self.open_valves(wall)
        if cleanout:
            tag = wall.one("cleanout")["tag"]
            # Tapping the pipe is free of washers; opening the plug is not.
            if "full" in self.do("inspect", tag=tag).text:
                self.bucket_under(tag)
                self.do("open_joint", tag=tag)
                self.do("repair", tag=tag, method="clear")
                self.diag.add("branch_clog")
                self.do("close_joint", tag=tag)
                self.blocked = {}
                changed = True
            self.cleanout_checked = True
        self.need_utility = False
        return changed

    # ------------------------------------------------------------- run

    def run(self) -> None:
        try:
            self.do("briefing")
            for fx in FIXTURES:
                self.stop_leaks(fx)  # a running leak costs more every tick it is left
            if self.pending_main:
                self.utility(False)
            pending = list(FIXTURES)
            for _ in range(10):
                for fx in sorted(pending, key=lambda f: f != self.room):
                    other = FIXTURES[1 - FIXTURES.index(fx)]
                    trap_ok = self.cleanout_checked or self.blocked.get(other) is False
                    self.service(fx, trap_ok)
                    if self.pending_main:
                        break
                stuck = [fx for fx in FIXTURES if self.blocked.get(fx)]
                want_cleanout = len(stuck) == 2 and not self.cleanout_checked
                if (self.pending_main or self.need_utility or want_cleanout) and self.utility_visits < 4:
                    changed = self.utility(want_cleanout or (self.need_utility and bool(stuck)
                                                              and not self.cleanout_checked))
                    pending = list(FIXTURES) if changed else stuck
                elif stuck:
                    pending = stuck
                else:
                    pending = [fx for fx in FIXTURES if not self.clean.get(fx)]
                if not pending:
                    break
            self.do("finish", diagnosis=sorted(self.diag))
        except Done:
            pass


# ------------------------------------------------- run against a live server

def main() -> int:
    """Usage: solver.py [mcp url] [facts url]

    Connects to the PlumberBench MCP server and plays one episode. The second
    argument is only needed when the server runs with facts switched off.
    """
    import asyncio
    import queue
    import threading
    import urllib.request

    from mcp.client.session import ClientSession
    try:
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

    url = sys.argv[1] if len(sys.argv) > 1 else "http://mcp-server:8000/mcp"
    facts_url = sys.argv[2] if len(sys.argv) > 2 else None
    requests: queue.Queue = queue.Queue()
    replies: queue.Queue = queue.Queue()

    async def pump():
        async with streamablehttp_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                while True:
                    item = await asyncio.to_thread(requests.get)
                    if item is None:
                        return
                    result = await session.call_tool(*item)
                    replies.put("\n".join(c.text for c in result.content if getattr(c, "text", None)))

    def call(tool, args):
        requests.put((tool, args))
        return replies.get()

    def facts_source():
        with urllib.request.urlopen(facts_url, timeout=10) as r:
            return json.loads(r.read())

    worker = threading.Thread(target=lambda: asyncio.run(pump()), daemon=True)
    worker.start()
    Solver(call, facts_source if facts_url else None,
           log=lambda tool, args, line: print(f"{tool} {args} -> {line}", flush=True)).run()
    requests.put(None)
    worker.join(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
