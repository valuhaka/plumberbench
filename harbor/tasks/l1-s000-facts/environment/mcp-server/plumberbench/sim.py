"""The rules of the world.

`apply(state, tool, args)` is the only function that changes a `State`. It is
deterministic: no randomness, no wall-clock time, no floating point.

Time moves in ticks. Each tick, in this order:
  1. supply: every faulty supply joint that is under pressure lets out 1 unit;
     an undone joint under pressure sprays SPRAY_RATE units
  2. taps: each running tap side with flow adds 1 unit to its basin
  3. drains: each basin sends up to DRAIN_RATE units down its drain; the water
     stops at the first blockage, or comes out at the first opening
  4. overflow: anything above BASIN_CAP goes on the floor
"""
from __future__ import annotations

from .world import (
    BASIN_CAP,
    BUCKET_CAP,
    COST,
    DIAGNOSES,
    DRAIN_RATE,
    FIXTURES,
    PRESSURE,
    ROOMS,
    SIDES,
    SPRAY_RATE,
    VIEWS,
    Comp,
    State,
    drain_chain,
    supply_chain,
)


class ActionError(Exception):
    """The action cannot be done. Nothing changes and no time passes."""


# ---------------------------------------------------------------- water

def _emit(s: State, c: Comp, units: int, catchable: bool = True) -> None:
    c.wet_tick = s.tick
    s.emitted += units
    if catchable and s.bucket_at == c.id:
        into = min(units, BUCKET_CAP - s.bucket_fill)
        s.bucket_fill += into
        units -= into
    if units > 0:
        c.puddle += units
        s.damage += units


def is_wet(s: State, c: Comp) -> bool:
    """A joint shows wet while it is letting water out. A repaired joint is wiped dry."""
    return c.wet_tick == s.tick and (c.fault is not None or c.open)


def supply(s: State, emit: bool = False) -> dict[tuple[str, str], int]:
    """Flow each tap side would give if opened now (0 none, 1 weak, 2 full).

    With `emit`, also lets water out of leaking and undone supply joints.
    """
    flows = {}
    for fx in FIXTURES:
        for side in SIDES:
            p = 2
            for cid in supply_chain(fx, side):
                c = s.comps[cid]
                if c.kind == "valve":
                    p = min(p, PRESSURE[c.pos])
                    continue
                if p > 0 and emit:
                    if c.open:
                        _emit(s, c, SPRAY_RATE, catchable=False)
                    elif c.fault:
                        _emit(s, c, 1)
                if c.open:
                    p = 0
            if s.comps[f"aer.{fx}"].fault:
                p = min(p, 1)
            flows[(fx, side)] = p
    return flows


def _drain(s: State, fx: str) -> None:
    level = s.basin[fx]
    if level <= 0:
        return
    leaky = []          # closed faulty joints that have water at them
    outlet = None       # where the water leaves the pipework, if it does
    blocked = False
    for cid in drain_chain(fx):
        c = s.comps[cid]
        if c.open:
            outlet = c
            break
        if c.kind == "joint":
            if c.fault:
                leaky.append(c)
        elif c.fault:   # clogged trap, or clogged branch behind the cleanout
            blocked = True
            break
    if not blocked:
        moved = min(level, DRAIN_RATE)
        s.basin[fx] -= moved
        if outlet is not None:
            _emit(s, outlet, moved)
    for j in leaky:
        _emit(s, j, 1)


def _reaches_branch(s: State, fx: str) -> bool:
    """True if water standing in this basin extends down to the shared branch."""
    return not any(s.comps[cid].open or s.comps[cid].kind == "trap" and s.comps[cid].fault
                   for cid in drain_chain(fx)[:-1])


def _tick(s: State, taps: dict[str, tuple[str, ...]] | None) -> None:
    s.tick += 1
    flows = supply(s, emit=True)
    if taps:
        s.flow, s.flow_tick = {}, s.tick
        for fx, sides in taps.items():
            for side in sides:
                f = flows[(fx, side)]
                s.flow.setdefault(fx, {})[side] = f
                if f > 0:
                    s.basin[fx] += 1
    for fx in FIXTURES:
        _drain(s, fx)
    for fx in FIXTURES:
        over = s.basin[fx] - BASIN_CAP
        if over > 0:
            s.basin[fx] = BASIN_CAP
            s.overflow[fx] += over
            s.damage += over
            s.emitted += over


def advance(s: State, ticks: int, taps: dict | None = None) -> bool:
    """Let time pass. Returns False if the time budget ran out on the way."""
    for _ in range(ticks):
        if s.tick >= s.budget:
            break
        _tick(s, taps)
    if s.tick >= s.budget:
        s.done = s.timed_out = True
        return False
    return True


# -------------------------------------------------------------- helpers

def _here(s: State, tag: str, kinds: tuple[str, ...] | None = None) -> Comp:
    c = s.by_tag(tag)
    if c is None:
        raise ActionError(f"There is no part tagged {tag}.")
    if c.room != s.room:
        raise ActionError(f"{c.tag} is not in this room.")
    if kinds and c.kind not in kinds:
        raise ActionError(f"{c.tag} is a {c.kind}; this needs a {' or '.join(kinds)}.")
    return c


def _ticks(value, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ActionError("ticks must be a whole number.") from None
    if not low <= n <= high:
        raise ActionError(f"ticks must be between {low} and {high}.")
    return n


def _opened(c: Comp) -> str:
    return {"joint": "undone", "trap": "removed", "cleanout": "open"}[c.kind]


def _inside(c: Comp) -> str:
    return "packed with sludge" if c.fault else "clear inside"


# -------------------------------------------------------------- actions

def _go(s, room):
    room = str(room).strip().lower()
    if room not in ROOMS:
        raise ActionError(f"Rooms are: {', '.join(ROOMS)}.")
    if room == s.room:
        raise ActionError(f"You are already in the {room}.")
    s.room, s.view = room, VIEWS[room][0]
    advance(s, COST["go"])
    return f"You walked to the {room}{' room' if room == 'utility' else ''}."


def _look(s, view):
    view = str(view).strip().lower()
    if view not in VIEWS[s.room]:
        raise ActionError(f"Views in the {s.room} are: {', '.join(VIEWS[s.room])}.")
    s.view = view
    what = {"counter": "the counter", "under_sink": "the pipes under the sink", "wall": "the wall of pipes"}
    return f"You are looking at {what[view]}."


def _inspect(s, tag):
    c = _here(s, tag)
    advance(s, COST["inspect"])
    if c.kind == "valve":
        word = {"open": "fully open", "half": "half open", "closed": "closed"}[c.pos]
        return f"{c.tag}: the valve is {word}."
    if c.kind == "joint":
        if c.open:
            return f"{c.tag} is undone."
        nut = "turns by hand, it is loose" if c.fault == "loose" else "is tight"
        seep = " Water is seeping from it." if is_wet(s, c) else ""
        return f"{c.tag}: the nut {nut}.{seep}"
    if c.kind == "aerator":
        return f"{c.tag}: the screen is " + ("crusted with limescale." if c.fault else "clean.")
    if c.open:
        return f"{c.tag} is {_opened(c)}. It is {_inside(c)}."
    if c.kind == "cleanout":
        full = c.fault and any(s.basin[fx] > 0 and _reaches_branch(s, fx) for fx in FIXTURES)
        return f"{c.tag}: you tap the pipe behind the plug. It sounds " + (
            "full of water." if full else "hollow.")
    return f"{c.tag} looks sound from outside. You cannot see inside without removing it."


def _run_tap(s, side, ticks):
    if s.room not in FIXTURES:
        raise ActionError("There is no tap in this room.")
    side = str(side).strip().lower()
    if side not in ("cold", "hot", "both"):
        raise ActionError("side must be cold, hot or both.")
    n = _ticks(ticks, 1, 5)
    sides = SIDES if side == "both" else (side,)
    advance(s, n, taps={s.room: sides})
    name = "both taps" if side == "both" else f"the {side} tap"
    return f"You ran {name} for {n} tick{'s' if n > 1 else ''}, then turned it off."


def _wait(s, ticks):
    n = _ticks(ticks, 1, 10)
    advance(s, n)
    return f"You waited {n} tick{'s' if n > 1 else ''}."


def _set_valve(s, tag, position):
    c = _here(s, tag, ("valve",))
    position = str(position).strip().lower()
    if position not in PRESSURE:
        raise ActionError("position must be open, half or closed.")
    if c.pos == position:
        raise ActionError(f"{c.tag} is already {position}.")
    c.pos = position
    advance(s, COST["set_valve"])
    return f"You turned {c.tag} to {position}."


def _place_bucket(s, tag):
    c = _here(s, tag, ("joint", "trap", "cleanout"))
    if s.bucket_at == c.id:
        raise ActionError(f"The bucket is already under {c.tag}.")
    s.bucket_at, s.bucket_fill = c.id, 0
    advance(s, COST["place_bucket"])
    return f"You emptied the bucket and set it under {c.tag}."


def _open_joint(s, tag):
    c = _here(s, tag, ("joint", "trap", "cleanout"))
    if c.open:
        raise ActionError(f"{c.tag} is already {_opened(c)}.")
    c.open = True
    if c.kind == "trap":
        _emit(s, c, 1)  # the water that sits in the bend
    advance(s, COST["open_joint"])
    if c.kind == "joint":
        return f"You undid {c.tag}."
    return f"You {'removed' if c.kind == 'trap' else 'opened'} {c.tag}. It is {_inside(c)}."


def _close_joint(s, tag):
    c = _here(s, tag, ("joint", "trap", "cleanout"))
    if not c.open:
        raise ActionError(f"{c.tag} is not {_opened(c)}.")
    if s.washers <= 0:
        raise ActionError(f"You have no washers left, so {c.tag} cannot be refitted.")
    if not advance(s, COST["close_joint"]):
        return f"Time ran out while you were refitting {c.tag}."
    s.washers -= 1
    c.open = False
    if c.kind == "joint":
        c.fault = None  # a joint refitted on a new washer is sound
    return f"You refitted {c.tag} with a new washer."


def _repair(s, tag, method):
    c = _here(s, tag)
    method = str(method).strip().lower()
    if method == "tighten":
        if c.kind != "joint":
            raise ActionError("Only joints can be tightened.")
        if c.open:
            raise ActionError(f"{c.tag} is undone. Refit it first.")
    elif method == "clear":
        if c.kind not in ("trap", "cleanout", "aerator"):
            raise ActionError("Only traps, the cleanout and aerators can be cleared.")
        if c.kind != "aerator" and not c.open:
            raise ActionError(f"{c.tag} must be {_opened(c)} before it can be cleared.")
    else:
        raise ActionError("method must be tighten or clear.")

    if not advance(s, COST["repair"]):
        return f"Time ran out while you were working on {c.tag}."
    if method == "tighten":
        if c.fault == "loose":
            c.fault = None
            return f"You tightened {c.tag}. The nut took a full turn and is now snug."
        if c.fault is None:
            c.fault = "worn"  # forcing a tight nut crushes the washer
            return f"{c.tag} was already tight. You forced it and felt the washer give."
        return f"{c.tag} was already tight. Forcing it changed nothing."
    c.fault = None
    return f"You cleared {c.tag}."


def _finish(s, diagnosis):
    if isinstance(diagnosis, str):
        diagnosis = [d for d in diagnosis.replace(",", " ").split() if d]
    names = sorted({str(d).strip().lower() for d in (diagnosis or [])})
    bad = [d for d in names if d not in DIAGNOSES]
    if bad:
        raise ActionError(f"Unknown diagnosis {bad}. Choose from: {', '.join(DIAGNOSES)}.")
    s.diagnosis = names
    s.done = True
    return "You packed up and reported the job finished."


def _briefing(s):
    return f'The tenant says: "{s.complaint}"'


ACTIONS = {
    "briefing": (_briefing, ()),
    "go": (_go, ("room",)),
    "look": (_look, ("view",)),
    "inspect": (_inspect, ("tag",)),
    "run_tap": (_run_tap, ("side", "ticks")),
    "wait": (_wait, ("ticks",)),
    "set_valve": (_set_valve, ("tag", "position")),
    "place_bucket": (_place_bucket, ("tag",)),
    "open_joint": (_open_joint, ("tag",)),
    "close_joint": (_close_joint, ("tag",)),
    "repair": (_repair, ("tag", "method")),
    "finish": (_finish, ("diagnosis",)),
}


def apply(s: State, tool: str, args: dict) -> str:
    """Carry out one action and return a one-line account of it."""
    if tool not in ACTIONS:
        raise ActionError(f"Unknown tool {tool}.")
    if s.done:
        raise ActionError("The job is over.")
    fn, names = ACTIONS[tool]
    missing = [n for n in names if n not in args]
    if missing:
        raise ActionError(f"{tool} needs: {', '.join(names)}.")
    msg = fn(s, *[args[n] for n in names])
    s.step += 1
    if s.timed_out and "Time ran out" not in msg:
        msg += " Time is up."
    return msg
