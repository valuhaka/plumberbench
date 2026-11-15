"""Seeded task generator. Same (seed, level) always gives the same house."""
from __future__ import annotations

import copy
import random

from . import layout as pipes
from .sim import _tick
from .world import FIXTURES, LATE_MAX, SIDES, Comp, State, supply_chain, PRESSURE

# Difficulty ladder. Each level adds one kind of decision, not smaller pixels.
# Level 5 closes what gives levels 1-4 away: the fault count varies while the budget and
# washers do not, the tenant says only where the trouble is, the room of a drip is not
# heard, and two faults show only to a test made at the right time: a weak washer past a
# closed valve that fails some ticks after the valve is opened (`late`), and a trap that
# drains at half speed, which only running both taps shows (`partial`).
LEVELS = {
    1: dict(faults=1, masked=False, vague=False, decoys=0, budget=45, washers=2),
    2: dict(faults=1, masked=False, vague=True, decoys=1, budget=45, washers=2),
    3: dict(faults=2, masked=True, vague=True, decoys=1, budget=55, washers=3),
    4: dict(faults=3, masked=True, vague=True, decoys=2, budget=65, washers=4),
    5: dict(faults=(2, 3), masked=True, vague="where", decoys=2, budget=120, washers=6, late=0.6, partial=0.4,
            mopped=True),
}

FAULT_TYPES = (
    "trap_clog",
    "branch_clog",
    "supply_leak",
    "drain_leak",
    "aerator_clog",
    "valve_not_open",
)

MASKED_PAIRS = ("clog_hides_leak", "closed_valve_hides_leak", "valve_hides_aerator", "branch_hides_trap")


def _house() -> dict[str, Comp]:
    comps: dict[str, Comp] = {}

    def add(cid, kind, room, view, **kw):
        comps[cid] = Comp(id=cid, tag="", kind=kind, room=room, view=view, **kw)

    add("main", "valve", "utility", "wall", line="cold", role="main")
    add("heater", "valve", "utility", "wall", line="cold", role="heater")
    add("spare", "valve", "utility", "wall", line="cold", role="spare", pos="closed")
    add("cleanout", "cleanout", "utility", "wall", line="drain")
    for fx in FIXTURES:
        for side in SIDES:
            add(f"branch.{fx}.{side}", "valve", "utility", "wall", line=side, role="branch")
            add(f"jin.{fx}.{side}", "joint", fx, "under_sink", line=side, role="wall_side")
            add(f"stop.{fx}.{side}", "valve", fx, "under_sink", line=side, role="stop")
            add(f"jhose.{fx}.{side}", "joint", fx, "under_sink", line=side, role="tap_side")
        add(f"jtail.{fx}", "joint", fx, "under_sink", line="drain", role="above_trap")
        add(f"trap.{fx}", "trap", fx, "under_sink", line="drain")
        add(f"jarm.{fx}", "joint", fx, "under_sink", line="drain", role="below_trap")
        add(f"aer.{fx}", "aerator", fx, "counter")
    return comps


def _fault(rng: random.Random, kind: str, fx: str | None = None, side: str | None = None) -> dict:
    fx = fx or rng.choice(("kitchen", "kitchen", "bathroom"))
    side = side or rng.choice(SIDES)
    cause = rng.choice(("loose", "worn"))
    if kind == "trap_clog":
        return {"type": kind, "id": f"trap.{fx}"}
    if kind == "branch_clog":
        return {"type": kind, "id": "cleanout"}
    if kind == "supply_leak":
        where = rng.choice(("jin", "jhose"))
        return {"type": kind, "id": f"{where}.{fx}.{side}", "cause": cause}
    if kind == "drain_leak":
        where = rng.choice(("jtail", "jarm"))
        return {"type": kind, "id": f"{where}.{fx}", "cause": cause}
    if kind == "aerator_clog":
        return {"type": kind, "id": f"aer.{fx}"}
    if kind == "valve_not_open":
        vid = rng.choice((f"stop.{fx}.{side}", f"branch.{fx}.{side}", "heater"))
        return {"type": kind, "id": vid, "pos": rng.choice(("half", "half", "closed"))}
    raise ValueError(kind)


def _masked_pair(rng: random.Random) -> list[dict]:
    """Two faults where the first hides the second until it is fixed."""
    fx = rng.choice(("kitchen", "kitchen", "bathroom"))
    side = rng.choice(SIDES)
    cause = rng.choice(("loose", "worn"))
    kind = rng.choice(MASKED_PAIRS)
    if kind == "clog_hides_leak":
        return [{"type": "trap_clog", "id": f"trap.{fx}"},
                {"type": "drain_leak", "id": f"jarm.{fx}", "cause": cause}]
    if kind == "closed_valve_hides_leak":
        return [{"type": "valve_not_open", "id": f"stop.{fx}.{side}", "pos": "closed"},
                {"type": "supply_leak", "id": f"jhose.{fx}.{side}", "cause": cause}]
    if kind == "valve_hides_aerator":
        vid = rng.choice((f"stop.{fx}.{side}", f"branch.{fx}.{side}"))
        return [{"type": "valve_not_open", "id": vid, "pos": "closed"},
                {"type": "aerator_clog", "id": f"aer.{fx}"}]
    return [{"type": "branch_clog", "id": "cleanout"},
            {"type": "trap_clog", "id": f"trap.{fx}"}]


def _fixture_of(cid: str) -> str | None:
    for fx in FIXTURES:
        if fx in cid:
            return fx
    return None


def _pick_faults(rng: random.Random, cfg: dict) -> list[dict]:
    faults = _masked_pair(rng) if cfg["masked"] else [_fault(rng, rng.choice(FAULT_TYPES))]
    count = cfg["faults"] if isinstance(cfg["faults"], int) else rng.randint(*cfg["faults"])
    while len(faults) < count:
        cand = _fault(rng, rng.choice(FAULT_TYPES))
        if any(cand["id"] == f["id"] for f in faults):
            continue
        faults.append(cand)
    taken = {f["id"] for f in faults}
    if cfg.get("late") and rng.random() < cfg["late"]:  # levels 1-4 draw nothing here
        # A valve left closed, and past it a weak washer that holds until the water is back on
        # it: it starts dripping some ticks after that valve is opened, never before.
        pairs = [(f"stop.{fx}.{side}", f"jhose.{fx}.{side}") for fx in FIXTURES for side in SIDES]
        pairs += [(f"branch.{fx}.{side}", f"{j}.{fx}.{side}") for fx in FIXTURES for side in SIDES for j in ("jin", "jhose")]
        pairs = [(v, j) for v, j in pairs if v not in taken and j not in taken
                 and not any(f["type"] == "valve_not_open" and f["id"] in supply_chain(_fixture_of(j), j.split(".")[2])
                             for f in faults)]
        if pairs:
            valve, joint = rng.choice(pairs)
            faults.append({"type": "valve_not_open", "id": valve, "pos": "closed"})
            faults.append({"type": "supply_leak", "id": joint, "cause": "worn", "late": rng.randint(3, LATE_MAX)})
            taken |= {valve, joint}
            # Often a second valve left closed, with sound joints past it: which one to watch?
            others = [f"stop.{fx}.{side}" for fx in FIXTURES for side in SIDES]
            others = [v for v in others if v not in taken and _fixture_of(v) + v.split(".")[2] != _fixture_of(joint) + joint.split(".")[2]
                      and not any(f["id"] in supply_chain(_fixture_of(v), v.split(".")[2]) for f in faults
                                  if f["type"] in ("supply_leak", "valve_not_open"))]
            if others and rng.random() < 0.6:
                decoy = rng.choice(others)
                faults.append({"type": "valve_not_open", "id": decoy, "pos": "closed"})
                taken.add(decoy)
    if cfg.get("partial") and rng.random() < cfg["partial"]:
        free = [f"trap.{fx}" for fx in FIXTURES if f"trap.{fx}" not in taken]
        if free:
            faults.append({"type": "trap_clog", "id": rng.choice(free), "partial": True})
    return faults


def _where(fault: dict) -> tuple[str, str]:
    """Fixture and side a complaint about this fault would mention."""
    parts = fault["id"].split(".")
    fx = _fixture_of(fault["id"]) or "kitchen"
    side = parts[-1] if parts[-1] in SIDES else "hot"
    return fx, side


WHERE_ONLY = (
    "Something is not right with the {sink}.",
    "Can you look at the {sink}? It has been acting up all week.",
    "The {sink} is giving us trouble. I don't know what is wrong with it.",
)


def _complaint(fault: dict, vague, rng: random.Random | None = None) -> str:
    kind = fault["type"]
    fx, side = _where(fault)
    sink = "kitchen sink" if fx == "kitchen" else "bathroom basin"
    if vague == "where":  # level 5: where the trouble is (or seems to be), nothing about what it is
        if rng.random() < 0.25:
            sink = "bathroom basin" if fx == "kitchen" else "kitchen sink"  # the wrong room
        return rng.choice(WHERE_ONLY).format(sink=sink)
    if kind == "trap_clog":
        if vague:
            return f"The {sink} keeps backing up. I think the big drain pipe in the utility room is blocked."
        return f"The {sink} will not drain. Water just sits in it."
    if kind == "branch_clog":
        if vague:
            return "The kitchen sink is blocked. It is probably grease in the trap again."
        return "Neither the kitchen sink nor the bathroom basin will drain."
    if kind == "supply_leak":
        if vague:
            return f"The cabinet under the {sink} is wet. The drain must be leaking."
        return f"Water drips from a fitting under the {sink}, even when the tap is off."
    if kind == "drain_leak":
        if vague:
            return f"I keep finding water under the {sink}. I think one of the water pipes is leaking."
        return f"Water drips under the {sink}, but only when water is going down the drain."
    if kind == "aerator_clog":
        if vague:
            return f"The tap at the {sink} barely runs. Someone must have turned a valve down."
        return f"Hot and cold both come out weak at the {sink} tap. The other tap is fine."
    if kind == "valve_not_open":
        everywhere = fault["id"] == "heater"
        place = "every tap" if everywhere else f"the {sink} tap"
        if fault["pos"] == "closed":
            if vague:
                return f"No {side if not everywhere else 'hot'} water at {place}. Something must be blocked inside the tap."
            return f"There is no {side if not everywhere else 'hot'} water at {place}."
        if vague:
            return f"The water is weak at {place}. The nozzle on the tap is probably clogged."
        return f"The {side if not everywhere else 'hot'} water is weak at {place}."
    raise ValueError(kind)


def _pressure_at(comps: dict[str, Comp], joint_id: str) -> int:
    _, fx, side = joint_id.split(".")
    p = 2
    for cid in supply_chain(fx, side):
        if cid == joint_id:
            return p
        c = comps[cid]
        if c.kind == "valve":
            p = min(p, PRESSURE[c.pos])
    return p


def generate(seed: int, level: int, faults: list[dict] | None = None) -> State:
    """Build the house for (seed, level). Pass `faults` to hand-author a case."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {sorted(LEVELS)}")
    cfg = LEVELS[level]
    rng = random.Random(f"plumberbench:{level}:{seed}")
    comps = _house()
    faults = [dict(f) for f in faults] if faults is not None else _pick_faults(rng, cfg)

    basin = {f: 0 for f in FIXTURES}
    for f in faults:
        c = comps[f["id"]]
        if f.get("partial"):
            c.fault = "partial"
        elif f.get("late"):
            c.late = f["late"]  # sound for now; the washer gives after this many ticks under pressure
        elif f["type"] in ("trap_clog", "branch_clog", "aerator_clog"):
            c.fault = "clog"
        elif f["type"] in ("supply_leak", "drain_leak"):
            c.fault = f["cause"]
        else:
            c.pos = f["pos"]

    # Evidence the fault has already left behind. At level 5 the tenant has mopped the floor
    # and bailed out the basins before you came: only old dry stains are left.
    mopped = cfg.get("mopped", False)
    for f in faults:
        if mopped:
            continue
        if f["type"] == "trap_clog" and not f.get("partial"):
            basin[_fixture_of(f["id"])] = rng.randint(2, 4)
        elif f["type"] == "branch_clog":
            basin["kitchen"] = max(basin["kitchen"], rng.randint(2, 4))
            basin["bathroom"] = max(basin["bathroom"], rng.randint(1, 2))
    for f in faults:
        c = comps[f["id"]]
        if f.get("late"):
            continue  # nothing to see until it gives
        if f["type"] == "supply_leak":
            if _pressure_at(comps, c.id) > 0 and not mopped:
                c.puddle = 2
            else:
                c.stain = True
        elif f["type"] == "drain_leak":
            fx = _fixture_of(c.id)
            hidden = c.role == "below_trap" and comps[f"trap.{fx}"].fault
            if hidden or mopped:
                c.stain = rng.random() < 0.5
            else:
                c.puddle = 1

    # Decoys: old dry stains under sound joints.
    sound = sorted(cid for cid, c in comps.items() if c.kind == "joint" and not c.fault and not c.stain)
    for cid in rng.sample(sound, cfg["decoys"]):
        comps[cid].stain = True

    # Tags carry no information: numbering is shuffled per seed.
    for kind, prefix in (("valve", "V"), ("joint", "J"), ("trap", "T"), ("cleanout", "C"), ("aerator", "A")):
        ids = sorted(cid for cid, c in comps.items() if c.kind == kind)
        nums = list(range(1, len(ids) + 1))
        rng.shuffle(nums)
        for cid, n in zip(ids, nums):
            comps[cid].tag = f"{prefix}{n}"

    cold = [f"branch.{fx}.cold" for fx in FIXTURES] + ["spare"]
    hot = [f"branch.{fx}.hot" for fx in FIXTURES]
    rng.shuffle(cold)
    rng.shuffle(hot)

    state = State(
        seed=seed,
        level=level,
        budget=cfg["budget"],
        comps=comps,
        complaint=_complaint(faults[0], cfg["vague"], rng),
        faults=faults,
        initial_pos={cid: c.pos for cid, c in comps.items() if c.kind == "valve"},
        manifold={"cold": cold, "hot": hot},
        washers=cfg["washers"],
        basin=basin,
        # Its own random stream: the layout varies without changing which faults a seed gets.
        layout={fx: pipes.sample(random.Random(f"plumberbench-layout:{level}:{seed}:{fx}")) for fx in FIXTURES},
    )
    # A leak that is running now is visibly wet now: probe one tick on a copy.
    probe = copy.deepcopy(state)
    _tick(probe, None)
    for cid, c in probe.comps.items():
        if c.wet_tick == 1:
            state.comps[cid].wet_tick = 0
    return state
