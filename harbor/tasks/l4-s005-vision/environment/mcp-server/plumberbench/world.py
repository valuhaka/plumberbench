"""World state for PlumberBench.

The house is small and fixed in shape: a kitchen sink, a bathroom basin and a
utility room. What changes per seed is which parts are faulty, what the tenant
says, which tags the parts carry and the order of the manifold valves.

Everything the simulator, the renderer and the judge need lives in `State`.
There is no other source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROOMS = ("kitchen", "bathroom", "utility")
FIXTURES = ("kitchen", "bathroom")
SIDES = ("cold", "hot")
VIEWS = {
    "kitchen": ("counter", "under_sink"),
    "bathroom": ("counter", "under_sink"),
    "utility": ("wall",),
}

BASIN_CAP = 8        # units a basin holds before it overflows
DRAIN_RATE = 2       # units per tick a clear drain carries
BUCKET_CAP = 10      # units the bucket holds
SPRAY_RATE = 3       # units per tick from an undone joint under pressure
DAMAGE_CAP = 20      # damage at which the damage part of the score reaches zero

PRESSURE = {"open": 2, "half": 1, "closed": 0}
FLOW_NAME = {0: "none", 1: "weak", 2: "full"}

COST = {
    "go": 2,
    "look": 0,
    "briefing": 0,
    "inspect": 3,
    "set_valve": 1,
    "place_bucket": 1,
    "open_joint": 3,
    "close_joint": 3,
    "repair": 3,
    "finish": 0,
}

DIAGNOSES = (
    "trap_clog",
    "branch_clog",
    "supply_leak",
    "drain_leak",
    "aerator_clog",
    "valve_not_open",
)

# What each fault type is. Shown to the agent (instruction, `finish` tool) and to
# people (terminal `help`, the browser's finish dialog) in exactly these words.
DIAGNOSIS_TEXT = {
    "trap_clog": "a blocked trap, the U-bend under a basin",
    "branch_clog": "a blocked drain branch, shared by both basins, behind the cleanout plug in the utility room",
    "supply_leak": "a leaking joint on a hot or cold supply line",
    "drain_leak": "a leaking joint on the drain under a basin",
    "aerator_clog": "a blocked aerator, the screen on the end of a tap's spout",
    "valve_not_open": "a valve that should be open, left closed or half open",
}


@dataclass
class Comp:
    """One tagged part. Fields that do not apply to a kind keep their default."""

    id: str                    # stable internal name, never shown to the agent
    tag: str                   # what the agent sees, shuffled per seed
    kind: str                  # valve | joint | trap | cleanout | aerator
    room: str
    view: str
    line: str = ""             # cold | hot | drain
    role: str = ""             # valve: main|heater|branch|spare|stop
                               # joint: wall_side|tap_side|above_trap|below_trap
    pos: str = "open"          # valve position: open | half | closed
    open: bool = False         # joint undone, trap removed, cleanout plug out
    fault: str | None = None   # joint: loose|worn ; trap, cleanout, aerator: clog
    puddle: int = 0            # water on the floor under this part
    stain: bool = False        # old dry stain, not water
    wet_tick: int = -99        # last tick this part let water out


@dataclass
class State:
    seed: int
    level: int
    budget: int
    comps: dict[str, Comp]
    complaint: str
    faults: list[dict]              # ground truth at the start
    initial_pos: dict[str, str]     # valve positions at the start
    manifold: dict[str, list[str]]  # valve ids left to right on each manifold
    washers: int = 2
    tick: int = 0
    step: int = 0
    damage: int = 0
    emitted: int = 0                # all water let out since the start
    room: str = "kitchen"
    view: str = "counter"
    basin: dict[str, int] = field(default_factory=lambda: {f: 0 for f in FIXTURES})
    overflow: dict[str, int] = field(default_factory=lambda: {f: 0 for f in FIXTURES})
    bucket_at: str | None = None    # comp id the bucket stands under
    bucket_fill: int = 0
    flow: dict[str, dict[str, int]] = field(default_factory=dict)
    flow_tick: int = -99            # tick the `flow` reading belongs to
    done: bool = False
    timed_out: bool = False
    diagnosis: list[str] | None = None
    layout: dict[str, dict] = field(default_factory=dict)  # pipe layout under each sink (layout.py)

    def by_tag(self, tag: str) -> Comp | None:
        tag = str(tag).strip().upper()
        for c in self.comps.values():
            if c.tag == tag:
                return c
        return None

    def in_view(self) -> list[Comp]:
        found = [c for c in self.comps.values() if c.room == self.room and c.view == self.view]
        return sorted(found, key=lambda c: (c.tag[0], int(c.tag[1:])))


def supply_chain(fixture: str, side: str) -> list[str]:
    """Parts between the street and the tap, in the order water meets them."""
    ids = ["main"]
    if side == "hot":
        ids.append("heater")
    ids += [
        f"branch.{fixture}.{side}",
        f"jin.{fixture}.{side}",
        f"stop.{fixture}.{side}",
        f"jhose.{fixture}.{side}",
    ]
    return ids


def drain_chain(fixture: str) -> list[str]:
    """Parts between the basin and the stack, in the order water meets them."""
    return [f"jtail.{fixture}", f"trap.{fixture}", f"jarm.{fixture}", "cleanout"]
