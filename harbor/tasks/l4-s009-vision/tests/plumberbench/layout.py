"""Where the pipes run under each sink: different in every house, never colliding.

A layout is a handful of numbers per fixture:

    hot_x, cold_x    where each supply comes out of the back wall (left, right,
                     or both on one side)
    hot_z, cold_z    how high it comes out
    trap_dir         +1: the trap's outlet is to the right of the tailpiece, -1: left
    trap_w           distance between the trap's two legs
    trap_bottom      height of the U-bend
    leg              height of the legs above the bend (the slip joints sit at the top)
    arm_rise         how far the outlet rises before the arm turns toward the wall
    arm_side         how far the arm runs sideways before it turns into the wall

`supply(layout, side)` and `drain(layout)` give the points every part is drawn
at. `solids(layout)` turns the same points into capsules, and `clearance(layout)`
checks every pair from different lines, every lever position and the cupboard's
walls. `sample` draws layouts until one passes, so a drawn house can never have
a pipe through another pipe, a lever through a hose, or a trap through a wall.
The scene builder draws from these same functions, so the check sees exactly
what is drawn.
"""
from __future__ import annotations

import math
import random

BACK_Y = 0.30            # the back wall of the cupboard
LINE_Y = 0.20            # supply risers stand this far out from the back wall
CAB_X = 0.45             # inner faces of the cupboard's side walls are at x = +-CAB_X
FRONT_Y = -0.30          # inside of the cupboard door
BASIN_Z = 0.62           # underside of the basin
TAP_INLET_X = 0.06       # the tap's two inlets under the basin are at x = -/+ this

R_SUPPLY, R_HOSE, R_NUT, R_VALVE, R_LEVER = 0.011, 0.008, 0.019, 0.023, 0.010
R_DRAIN, R_SLIP = 0.021, 0.028
LEVER_LEN = 0.085
CLEARANCE = 0.012        # the smallest gap allowed between parts of different lines

DEFAULT = {"hot_x": -0.34, "cold_x": 0.34, "hot_z": 0.16, "cold_z": 0.16, "trap_dir": 1,
           "trap_w": 0.12, "trap_bottom": 0.30, "leg": 0.13, "arm_rise": 0.035, "arm_side": 0.04}

Vec = tuple[float, float, float]


# ---------------------------------------------------------------- geometry

def supply(lay: dict, side: str) -> dict:
    """Points of one supply line, from the wall to the tap.

    Each flexible hose goes to the tap inlet on its own side (the line further
    left to the left inlet), so the two hoses never cross.
    """
    x, z = lay[f"{side}_x"], lay[f"{side}_z"]
    other = lay["cold_x" if side == "hot" else "hot_x"]
    inlet = -TAP_INLET_X if x < other else TAP_INLET_X
    return {
        "stub": ((x, BACK_Y, z), (x, LINE_Y, z)),
        "jin": (x, (BACK_Y + LINE_Y) / 2, z),             # wall-side joint, on the stub
        "riser": ((x, LINE_Y, z), (x, LINE_Y, z + 0.175)),
        "valve": (x, LINE_Y, z + 0.09),                     # stop valve
        "jhose": (x, LINE_Y, z + 0.185),                    # tap-side joint
        "hose": ((x, LINE_Y, z + 0.19), (inlet, 0.10, BASIN_Z)),
        "toward": 1.0 if x < 0 else -1.0,                   # levers turn toward the middle
    }


def lever(valve: Vec, toward: float, pos: str) -> tuple[Vec, Vec]:
    """The lever's capsule: in front of the valve, up when open, across when closed."""
    a = math.radians({"open": 0.0, "half": 45.0, "closed": 90.0}[pos])
    front = (valve[0], valve[1] - 0.04, valve[2])
    tip = (front[0] + toward * math.sin(a) * LEVER_LEN, front[1], front[2] + math.cos(a) * LEVER_LEN)
    return front, tip


def drain(lay: dict) -> dict:
    """Points of the drain, from the basin to the wall."""
    d, w = lay["trap_dir"], lay["trap_w"]
    zb = lay["trap_bottom"]
    z_in = zb + lay["leg"]              # inlet slip joint, at the top of the inlet leg
    z_out = z_in - 0.03                 # outlet slip joint sits a little lower
    z_arm = z_out + lay["arm_rise"]
    x_out = d * w
    x_turn = d * (w + lay["arm_side"])
    return {
        "tail": ((0.0, 0.0, BASIN_Z), (0.0, 0.0, z_in + 0.015)),
        "jtail": (0.0, 0.0, z_in),
        "trap_in": ((0.0, 0.0, z_in - 0.01), (0.0, 0.0, zb)),
        "bend": ((0.0, 0.0, zb), (x_out, 0.0, zb)),
        "trap_out": ((x_out, 0.0, zb), (x_out, 0.0, z_out - 0.01)),
        "jarm": (x_out, 0.0, z_out),
        "arm_up": ((x_out, 0.0, z_out + 0.015), (x_out, 0.0, z_arm)),
        "arm_side": ((x_out, 0.0, z_arm), (x_turn, 0.0, z_arm)),
        # Into the wall with a slight fall, as a trap arm should have.
        "arm_wall": ((x_turn, 0.0, z_arm), (x_turn, BACK_Y, z_arm - 0.008)),
        "trap_mid": (x_out / 2, 0.0, zb),
        "hole_in": (0.0, 0.0, z_in - 0.012),
        "hole_out": (x_out, 0.0, z_out - 0.012),
    }


def solids(lay: dict) -> list[tuple[str, str, Vec, Vec, float]]:
    """Every solid part as (line, name, a, b, radius). Levers appear once per position."""
    out = []
    for side in ("hot", "cold"):
        p = supply(lay, side)
        x, _, z = p["valve"]
        out += [
            (side, "stub", *p["stub"], R_SUPPLY),
            (side, "jin", _along(p["jin"], "y", 0.013), _along(p["jin"], "y", -0.013), R_NUT),
            (side, "riser", *p["riser"], R_SUPPLY),
            (side, "valve", (x, LINE_Y, z - 0.022), (x, LINE_Y, z + 0.022), R_VALVE),
            (side, "jhose", _along(p["jhose"], "z", -0.013), _along(p["jhose"], "z", 0.013), R_NUT),
            (side, "hose", *p["hose"], R_HOSE),
        ]
        out += [(side, f"lever.{pos}", *lever(p["valve"], p["toward"], pos), R_LEVER)
                for pos in ("open", "half", "closed")]
    q = drain(lay)
    out += [("drain", name, *q[name], R_DRAIN)
            for name in ("tail", "trap_in", "bend", "trap_out", "arm_up", "arm_side", "arm_wall")]
    out += [("drain", name, _along(q[name], "z", -0.013), _along(q[name], "z", 0.013), R_SLIP)
            for name in ("jtail", "jarm")]
    return out


def _along(p: Vec, axis: str, d: float) -> Vec:
    q = list(p)
    q["xyz".index(axis)] += d
    return tuple(q)


# --------------------------------------------------------------- the check

def _segment_distance(p1: Vec, q1: Vec, p2: Vec, q2: Vec) -> float:
    """Shortest distance between segments p1-q1 and p2-q2 (Ericson, Real-Time Collision Detection)."""
    d1 = [q - p for p, q in zip(p1, q1)]
    d2 = [q - p for p, q in zip(p2, q2)]
    r = [a - b for a, b in zip(p1, p2)]
    dot = lambda u, v: sum(a * b for a, b in zip(u, v))
    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    eps = 1e-12
    if a <= eps and e <= eps:
        s = t = 0.0
    elif a <= eps:
        s, t = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = dot(d1, r)
        if e <= eps:
            t, s = 0.0, min(max(-c / a, 0.0), 1.0)
        else:
            b = dot(d1, d2)
            denom = a * e - b * b
            s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > eps else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, min(max(-c / a, 0.0), 1.0)
            elif t > 1.0:
                t, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    c1 = [p + s * d for p, d in zip(p1, d1)]
    c2 = [p + t * d for p, d in zip(p2, d2)]
    return math.dist(c1, c2)


def clearance(lay: dict) -> list[str]:
    """Every problem with a layout; an empty list means it is physically sound."""
    problems = []
    parts = solids(lay)
    for line, name, a, b, r in parts:
        for p in (a, b):
            if abs(p[0]) + r > CAB_X - 0.005:
                problems.append(f"{line} {name} goes through a side wall")
            if p[2] - r < 0.005:
                problems.append(f"{line} {name} goes through the floor")
            if p[2] > BASIN_Z + 1e-9 or (name.startswith("lever") and p[2] + r > BASIN_Z):
                problems.append(f"{line} {name} goes into the basin")
            if p[1] > BACK_Y + 1e-9 or p[1] - r < FRONT_Y + 0.005:
                problems.append(f"{line} {name} goes through the back or the door")
    for i, (l1, n1, a1, b1, r1) in enumerate(parts):
        for l2, n2, a2, b2, r2 in parts[i + 1:]:
            if l1 == l2:
                continue  # parts of one line are built to fit together
            gap = _segment_distance(a1, b1, a2, b2) - r1 - r2
            if gap < CLEARANCE:
                problems.append(f"{l1} {n1} and {l2} {n2} are {gap * 1000:.0f} mm apart")
    return problems


# ---------------------------------------------------------------- sampling

def _draw(rng: random.Random) -> dict:
    mode = rng.choices(("split", "swapped", "both_left", "both_right"), (0.45, 0.15, 0.2, 0.2))[0]
    if mode in ("split", "swapped"):
        hot_x, cold_x = -rng.uniform(0.26, 0.38), rng.uniform(0.26, 0.38)
        if mode == "swapped":
            hot_x, cold_x = -hot_x, -cold_x
    else:
        # Both lines on one side, either one nearer the wall of the cupboard.
        outer = rng.uniform(0.33, 0.38)
        inner = outer - rng.uniform(0.11, 0.14)
        sign = -1 if mode == "both_left" else 1
        hot_x, cold_x = (sign * outer, sign * inner) if rng.random() < 0.5 else (sign * inner, sign * outer)
    same = mode.startswith("both")
    hot_z = rng.uniform(0.10, 0.22)
    cold_z = hot_z + rng.uniform(-0.03, 0.03) if same else rng.uniform(0.10, 0.22)
    return {
        "hot_x": round(hot_x, 3), "cold_x": round(cold_x, 3),
        "hot_z": round(hot_z, 3), "cold_z": round(cold_z, 3),
        "trap_dir": rng.choice((1, -1)),
        "trap_w": round(rng.uniform(0.10, 0.13), 3),
        "trap_bottom": round(rng.uniform(0.22, 0.34), 3),
        "leg": round(rng.uniform(0.10, 0.14), 3),
        "arm_rise": round(rng.uniform(0.02, 0.05), 3),
        "arm_side": round(rng.uniform(0.02, 0.14), 3),
    }


def sample(rng: random.Random, tries: int = 500) -> dict:
    """A random layout that passes `clearance`."""
    for _ in range(tries):
        lay = _draw(rng)
        if not clearance(lay):
            return lay
    return dict(DEFAULT)


def mode(lay: dict) -> str:
    """Which way round the supplies are, in words (for tests and debugging)."""
    h, c = lay["hot_x"], lay["cold_x"]
    if h < 0 < c:
        return "split"
    if c < 0 < h:
        return "swapped"
    return "both_left" if h < 0 else "both_right"
