"""Reference solver: a scripted plumber.

It has no access to the simulator. It calls the same tools as the agent and
reads only what comes back: the status line, the action text and the FACTS
list of what the current view shows. This file imports nothing from the rest
of the package, so it can be copied into a Harbor `solution/` folder as is.

Method, in short: stop any running leak first, then test every fixture, fix
what the tests point to, and test again, because one fault can hide another.
In a level 5 house (the only budget of LATE_BUDGET) a weak washer past a valve
found closed can give up to LATE_MAX ticks after that valve opens: so after opening
one it stays and watches the joints past it, and before finishing it waits that long
after the last valve it opened and looks under both sinks again. At level 5 `inspect`
answers in the close-up picture; the solver reads that picture's FACTS, which only an
`inspect` produces, so it pays for every look it takes.
"""
from __future__ import annotations

import json
import re
import sys

FIXTURES = ("kitchen", "bathroom")
LATE_BUDGET = 120  # level 5's budget, the same in every level 5 house
LATE_MAX = 10      # ticks under pressure a weak washer can hold (world.LATE_MAX)
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
        self.tick, self.budget = (int(m.group(2)), int(m.group(3))) if m else (None, None)
        self.facts = facts or []
        self.in_view: list[str] = []
        for line in text.splitlines():
            if line.startswith("FACTS: "):
                self.facts = json.loads(line[7:])
            elif line.startswith("IN VIEW: "):
                self.in_view = line[9:].split()

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
        self.view = "counter"
        self.where: dict[str, str] = {}   # tag -> the view it was seen in
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
        self.tick = 0
        self.budget = 0
        self.pressure_back = 0            # tick water last came back on somewhere
        self.dry: set[tuple[str, str]] = set()  # (fixture, side) whose tap last ran less than full
        self.opened: list[dict] = []      # valves found shut and opened by the last open_valves

    # ---------------------------------------------------------- plumbing

    def do(self, tool: str, **args) -> Seen:
        tag = args.get("tag")
        if tag and self.where.get(tag, self.view) != self.view:
            self.do("look", view=self.where[tag])  # parts can only be touched while in view
        text = self.call(tool, args)
        facts = None
        if "\nFACTS: " not in text and self.facts_source:
            facts = self.facts_source()
        seen = Seen(text, facts)
        self.log(tool, args, text.splitlines()[1] if "\n" in text else text)
        if seen.over:
            raise Done
        if seen.tick is not None:
            self.tick, self.budget = seen.tick, seen.budget
            if tool == "set_valve" and args.get("position") == "open" and not seen.error:
                self.pressure_back = seen.tick
        if seen.room:
            self.room, self.view = seen.room, seen.view
            for t in seen.in_view:
                self.where[t] = seen.view
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
        self.opened = []
        for v in seen.all("valve"):
            if v["role"] != "spare" and v["handle"] != "open":
                self.do("set_valve", tag=v["tag"], position="open")
                self.diag.add("valve_not_open")
                self.opened.append(v)
        if self.budget >= LATE_BUDGET:
            for v in [v for v in self.opened if v["role"] == "stop"]:
                self.watch(self.room, v["line"], ("tap_side",))
        return bool(self.opened)

    def watch(self, fx: str, line: str, where: tuple[str, ...]) -> None:
        """Level 5: a weak washer past a valve just opened gives within LATE_MAX ticks under
        pressure. Stay, with the bucket under it, and look every tick."""
        since = self.tick
        self.goto(fx)
        under = self.see("under_sink")
        joints = [j for j in under.all("joint", line=line, state="closed") if j["where"] in where]
        if not joints:
            return
        self.bucket_under(joints[0]["tag"])
        while self.tick < since + LATE_MAX:
            seen = self.do("wait", ticks=1)
            wet = [j for j in seen.all("joint", line=line, state="closed") if j["wet"] and j["where"] in where]
            if wet:
                self.fix_supply_leak(fx, wet[0], seen)
                return

    def loose(self, joint: dict) -> bool:
        """`inspect` says so, or at level 5 its close-up shows the nut backed off (FACTS `nut`)."""
        seen = self.do("inspect", tag=joint["tag"])
        close = seen.one("joint", tag=joint["tag"]) or {}
        return "loose" in seen.text or close.get("nut") == "backed off"

    def fix_supply_leak(self, fx: str, joint: dict, under: Seen) -> None:
        tag = joint["tag"]
        self.diag.add("supply_leak")
        self.bucket_under(tag)
        if self.loose(joint):
            self.do("repair", tag=tag, method="tighten")
            return
        if joint["where"] == "tap_side":
            stop = under.one("valve", role="stop", line=joint["line"])["tag"]
            self.do("set_valve", tag=stop, position="closed")
            self.swap_washer(tag)
            self.do("set_valve", tag=stop, position="open")
        else:
            # Upstream of its stop valve: only a valve in the utility room can take the pressure off.
            self.deferred.add(tag)
            self.pending_main.append((fx, tag, joint["line"]))

    def swap_washer(self, tag: str) -> None:
        self.do("open_joint", tag=tag)
        self.do("close_joint", tag=tag)  # refitting puts in a new washer

    def fix_drain_leak(self, joint: dict, level: int) -> None:
        tag = joint["tag"]
        self.diag.add("drain_leak")
        if level > 0:
            self.bucket_under(tag)  # standing water: it drips now and pours out if undone
        if self.loose(joint):
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
            for side in ("cold", "hot"):
                (self.dry.discard if tap[side] == "full" else self.dry.add)((fx, side))
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
                seen = self.do("inspect", tag=aerator)
                if "crusted" in seen.text or (seen.one("aerator", tag=aerator) or {}).get("scale"):
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
        changed = self.pressure_off_repairs()
        self.goto("utility")
        wall = self.see("wall")
        changed |= self.open_valves(wall)
        if self.budget >= LATE_BUDGET:  # watch past a branch valve found shut, where its tap ran dry
            for v in [v for v in self.opened if v["role"] == "branch"]:
                fed = [fx for fx, side in self.dry if side == v["line"]]
                if len(fed) == 1:
                    self.watch(fed[0], v["line"], ("wall_side", "tap_side"))
            changed |= self.pressure_off_repairs()  # a weak wall-side washer found while watching
            self.goto("utility")
            wall = self.see("wall")
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

    def pressure_off_repairs(self) -> bool:
        """Refit the wall-side joints waiting for the pressure to come off, from the utility room."""
        if not self.pending_main:
            return False
        self.goto("utility")
        wall = self.see("wall")
        if self.open_valves(wall):
            wall = self.see("wall")  # the levers as they are now
        shut = [wall.one("valve", role="main")["tag"]]
        if self.do("set_valve", tag=shut[0], position="closed").error:
            # Seized (level 5): shut every open branch valve on the lines that need it instead.
            lines = {line for _, _, line in self.pending_main}
            shut = [v["tag"] for v in wall.all("valve")
                    if v["role"] == "branch" and v["line"] in lines and v["handle"] == "open"]
            for t in shut:
                self.do("set_valve", tag=t, position="closed")
        for fx, tag, _ in self.pending_main:
            self.goto(fx)
            self.swap_washer(tag)
            self.deferred.discard(tag)
        self.pending_main = []
        self.goto("utility")
        for t in shut:
            self.do("set_valve", tag=t, position="open")
        return True

    def late_check(self) -> None:
        """Level 5: wait out the weakest washer after the last valve opened, then look again."""
        for _ in range(3):
            left = self.pressure_back + LATE_MAX - self.tick
            while left > 0:
                self.do("wait", ticks=min(10, left))
                left = self.pressure_back + LATE_MAX - self.tick
            found = False
            for fx in sorted(FIXTURES, key=lambda f: f != self.room):
                self.goto(fx)
                if any(j["wet"] for j in self.see("under_sink").all("joint", state="closed")):
                    found = True
                    self.stop_leaks(fx)
            if self.pending_main:
                self.utility(False)
            if not found:
                return

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
            if self.budget >= LATE_BUDGET:
                self.late_check()
            self.do("finish", diagnosis=sorted(self.diag))
        except Done:
            pass


# ------------------------------------------------- run against a live server

def main() -> int:
    """Usage: solver.py [mcp url] [--twin SEED LEVEL]

    Connects to the PlumberBench MCP server and plays one episode. In a
    pictures-only episode the server sends no FACTS, and the solver cannot see;
    with --twin it keeps its own copy of the house (the same seed, and every
    action copied into it: the simulation is deterministic, which is also how
    the verifier replays a job) and reads the FACTS from that. No secret, and
    nothing on the server the agent could find. It checks that the copy's
    STATUS line matches the server's after every action.
    """
    import asyncio
    import queue
    import threading

    from mcp.client.session import ClientSession
    try:
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

    argv = sys.argv[1:]
    twin = None
    if "--twin" in argv:
        i = argv.index("--twin")
        seed, level = int(argv[i + 1]), int(argv[i + 2])
        del argv[i:i + 3]
        from plumberbench import observe, sim
        from plumberbench.generate import generate
        twin = generate(seed, level)
    url = argv[0] if argv else "http://mcp-server:8000/mcp"
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
        reply = replies.get()
        if twin is not None:
            try:
                sim.apply(twin, tool, args)
            except sim.ActionError:
                pass  # refused on the server too: it still counts towards the free-action limit
            mine = "STATUS: " + observe.status(twin)
            theirs = next((line for line in reply.splitlines() if line.startswith("STATUS")), None)
            if theirs is not None and theirs != mine:
                raise SystemExit(f"The copy of the house drifted from the server:\n  {mine}\n  {theirs}")
        return reply

    def facts_source():
        return observe.facts(twin)

    worker = threading.Thread(target=lambda: asyncio.run(pump()), daemon=True)
    worker.start()
    try:
        Solver(call, facts_source if twin is not None else None,
               log=lambda tool, args, line: print(f"{tool} {args} -> {line}", flush=True)).run()
    finally:
        requests.put(None)  # always release the MCP thread, or an error would leave Python waiting on it
        worker.join(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
