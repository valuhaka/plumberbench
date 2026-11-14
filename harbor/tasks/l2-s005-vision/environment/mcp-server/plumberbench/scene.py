"""Scene description: which shapes the current view shows, built from `State`.

`build(state)` returns a `Scene`: a list of primitive shapes, the tag anchor
points and a camera. It is a pure function of the state, and it imports no GL,
so it can be tested anywhere.

Every shape that can ever appear in a view is always emitted, in the same
order; a shape that is absent right now is parked out of sight. That keeps the
shape list the same length within one house and view, so the renderer can
reuse its GL context and only update positions and colours.

Visual conventions (also stated in the task instruction):
  - a lever valve is open when its handle points along the pipe, closed when
    it points across it, and half open at 45 degrees
  - blue lines are cold, red lines are hot, grey pipes are drains
  - water is translucent blue; an old dry stain is brown; drips are blue beads
  - the bucket is translucent orange and shows how full it is
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .sim import is_wet
from .world import BASIN_CAP, BUCKET_CAP, FIXTURES, State

Vec = tuple[float, float, float]
RGBA = tuple[float, float, float, float]

COLD: RGBA = (0.20, 0.42, 0.88, 1)
HOT: RGBA = (0.88, 0.22, 0.18, 1)
BRASS: RGBA = (0.86, 0.70, 0.28, 1)
SLIP: RGBA = (0.48, 0.52, 0.58, 1)
PVC: RGBA = (0.94, 0.94, 0.91, 1)
DRAIN: RGBA = (0.36, 0.37, 0.40, 1)
STEEL: RGBA = (0.74, 0.76, 0.80, 1)
CERAMIC: RGBA = (0.96, 0.96, 0.97, 1)
HOSE: RGBA = (0.82, 0.82, 0.85, 1)
WOOD: RGBA = (0.64, 0.50, 0.35, 1)
COUNTER: RGBA = (0.30, 0.31, 0.34, 1)
WALL: RGBA = (0.88, 0.86, 0.82, 1)
FLOOR: RGBA = (0.58, 0.57, 0.55, 1)
WATER: RGBA = (0.22, 0.52, 0.98, 0.55)
SPRAY: RGBA = (0.40, 0.70, 1.00, 0.45)
DRIP: RGBA = (0.15, 0.45, 1.00, 1)
STAIN: RGBA = (0.42, 0.30, 0.16, 1)
SLUDGE: RGBA = (0.30, 0.22, 0.10, 1)
BUCKET: RGBA = (1.00, 0.55, 0.10, 0.30)
DARK: RGBA = (0.05, 0.05, 0.05, 1)
MARK: RGBA = (0.10, 0.10, 0.12, 1)
LEVER: RGBA = (0.08, 0.08, 0.09, 1)

HIDDEN_Z = -50.0
ANGLE = {"open": 0.0, "half": 45.0, "closed": 90.0}


@dataclass
class Shape:
    name: str
    type: str                  # box | cylinder | capsule | sphere
    rgba: RGBA
    size: tuple[float, ...]
    pos: Vec | None = None
    fromto: tuple[float, ...] | None = None
    quat: tuple[float, float, float, float] | None = None


@dataclass
class Scene:
    key: str                   # same key means same shape list, so GL can be reused
    camera_pos: Vec
    camera_target: Vec
    fovy: float = 45.0
    shapes: list[Shape] = field(default_factory=list)
    anchors: dict[str, Vec] = field(default_factory=dict)   # tag -> point it labels
    notes: dict[str, Vec] = field(default_factory=dict)     # small printed text, e.g. gauge numbers

    # -------------------------------------------------------------- builders

    def add(self, name, type_, rgba, size, pos=None, fromto=None, quat=None, show=True):
        if not show:
            rgba = (rgba[0], rgba[1], rgba[2], 0.0)
            if fromto is not None:
                fromto = (0, 0, HIDDEN_Z, 0, 0, HIDDEN_Z - 0.01)
            else:
                pos = (0.0, 0.0, HIDDEN_Z)
        self.shapes.append(Shape(f"{name}#{len(self.shapes)}", type_, rgba, tuple(size), pos,
                                 tuple(fromto) if fromto else None, quat))

    def pipe(self, name, a: Vec, b: Vec, r: float, rgba: RGBA, show=True):
        self.add(name, "capsule", rgba, (r,), fromto=(*a, *b), show=show)

    def box(self, name, center: Vec, half: Vec, rgba: RGBA, show=True):
        self.add(name, "box", rgba, half, pos=center, show=show)

    def disc(self, name, center: Vec, r: float, rgba: RGBA, show=True):
        self.add(name, "cylinder", rgba, (r, 0.0015), pos=center, show=show)


def _axis_offset(p: Vec, axis: str, d: float) -> Vec:
    i = "xyz".index(axis)
    q = list(p)
    q[i] += d
    return tuple(q)


def _nut(sc: Scene, name: str, at: Vec, axis: str, r: float, rgba: RGBA, undone: bool, slide: float):
    """A joint's nut, slid away along the pipe when undone, with the seam showing."""
    centre = _axis_offset(at, axis, slide) if undone else at
    sc.add(name, "cylinder", rgba, (r,),
           fromto=(*_axis_offset(centre, axis, -0.013), *_axis_offset(centre, axis, 0.013)))
    sc.add(name + ".seam", "cylinder", DARK, (r - 0.004,),
           fromto=(*_axis_offset(at, axis, -0.005), *_axis_offset(at, axis, 0.005)), show=undone)


def _lever(sc: Scene, name: str, stem: Vec, pos: str, length: float = 0.085):
    """Quarter-turn lever facing the camera (-y), pivoting in the x-z plane.

    Open: points up along the pipe. Closed: points across it. Half: 45 degrees.
    """
    a = math.radians(ANGLE[pos])
    dx, dz = math.sin(a), math.cos(a)
    front = (stem[0], stem[1] - 0.04, stem[2])
    tip = (front[0] + dx * length, front[1], front[2] + dz * length)
    sc.add(name + ".stem", "cylinder", STEEL, (0.006,), fromto=(*stem, *front))
    sc.add(name, "capsule", LEVER, (0.010,), fromto=(*front, *tip))


def _valve(sc: Scene, s: State, cid: str, at: Vec, pipe_r: float):
    c = s.comps[cid]
    sc.add(cid + ".body", "cylinder", BRASS, (pipe_r + 0.013,),
           fromto=(at[0], at[1], at[2] - 0.022, at[0], at[1], at[2] + 0.022))
    _lever(sc, cid + ".lever", at, c.pos)
    sc.anchors[c.tag] = at


def _floor_marks(sc: Scene, s: State, cid: str, at: Vec, floor_z: float = 0.0):
    """Puddle and old stain on the floor under a part."""
    c = s.comps[cid]
    x, y = at[0], at[1]
    sc.disc(cid + ".stain", (x + 0.03, y - 0.02, floor_z + 0.0012), 0.055, STAIN, show=c.stain)
    r = min(0.03 + 0.012 * c.puddle, 0.20)
    sc.disc(cid + ".puddle", (x, y, floor_z + 0.0025), r, WATER, show=c.puddle > 0)


def _drips(sc: Scene, s: State, cid: str, at: Vec):
    c = s.comps[cid]
    wet = is_wet(s, c) and not c.open
    side = -0.035 if at[0] > 0.2 else 0.035 if at[0] < -0.2 else 0.045  # clear of pipes and levers
    for i, dz in enumerate((0.035, 0.075, 0.115)):
        sc.add(f"{cid}.drip{i}", "sphere", DRIP, (0.0085 - 0.0012 * i,),
               pos=(at[0] + side, at[1] - 0.04, at[2] - dz), show=wet)


def _outflow(sc: Scene, s: State, cid: str, at: Vec, spray: bool):
    """Water leaving an undone part this tick: a jet under pressure, a stream otherwise."""
    c = s.comps[cid]
    flowing = c.open and c.wet_tick == s.tick
    if spray:
        sc.pipe(cid + ".jet1", at, (at[0] + 0.06, at[1] - 0.16, at[2] - 0.04), 0.018, SPRAY, show=flowing)
        sc.pipe(cid + ".jet2", at, (at[0] - 0.05, at[1] - 0.15, at[2] + 0.03), 0.014, SPRAY, show=flowing)
    else:
        sc.pipe(cid + ".fall", at, (at[0], at[1], 0.02), 0.010, SPRAY, show=flowing)


def _bucket(sc: Scene, s: State, spots: dict[str, Vec], floor_z: float = 0.0):
    """The bucket, if it stands under a part in this view."""
    at = spots.get(s.bucket_at) if s.bucket_at else None
    show = at is not None
    x, y = (at[0], at[1]) if at else (0.0, 0.0)
    h = 0.06
    sc.add("bucket", "cylinder", BUCKET, (0.10, h), pos=(x, y, floor_z + h), show=show)
    level = 0.11 * s.bucket_fill / BUCKET_CAP
    sc.add("bucket.water", "cylinder", WATER, (0.092, max(level / 2, 0.001)),
           pos=(x, y, floor_z + 0.004 + level / 2), show=show and s.bucket_fill > 0)


# ------------------------------------------------------------------ views

def _counter(s: State) -> Scene:
    fx = s.room
    sc = Scene(key=f"counter:{fx}", camera_pos=(0.0, -0.78, 1.30), camera_target=(0.0, 0.10, 0.80))
    bowl = STEEL if fx == "kitchen" else CERAMIC
    bottom, unit, rim = 0.66, 0.027, 0.90
    sc.box("floor", (0, -0.6, -0.01), (1.2, 1.0, 0.01), FLOOR)
    sc.box("cabinet", (0, -0.385, 0.435), (0.62, 0.005, 0.435), WOOD)
    sc.box("wall", (0, 0.40, 1.0), (0.9, 0.02, 0.6), WALL)
    sc.box("top.front", (0, -0.29, 0.885), (0.62, 0.10, 0.015), COUNTER)
    sc.box("top.back", (0, 0.29, 0.885), (0.62, 0.10, 0.015), COUNTER)
    sc.box("top.left", (-0.44, 0, 0.885), (0.18, 0.19, 0.015), COUNTER)
    sc.box("top.right", (0.44, 0, 0.885), (0.18, 0.19, 0.015), COUNTER)
    mid, half = (bottom + rim) / 2, (rim - bottom) / 2
    sc.box("bowl.bottom", (0, 0, bottom - 0.01), (0.26, 0.19, 0.01), bowl)
    sc.box("bowl.front", (0, -0.185, mid), (0.26, 0.005, half), bowl)
    sc.box("bowl.back", (0, 0.185, mid), (0.26, 0.005, half), bowl)
    sc.box("bowl.left", (-0.255, 0, mid), (0.005, 0.19, half), bowl)
    sc.box("bowl.right", (0.255, 0, mid), (0.005, 0.19, half), bowl)
    sc.disc("plughole", (0, 0, bottom + 0.0005), 0.03, DARK)
    # Level marks on the back of the bowl: one per unit of water, numbered.
    for k in range(1, BASIN_CAP + 1):
        z = bottom + unit * k
        sc.box(f"mark{k}", (-0.12, 0.1785, z), (0.05 if k % 4 else 0.08, 0.001, 0.0022), MARK)
        sc.notes[str(k)] = (-0.045, 0.178, z)

    level = s.basin[fx]
    top = bottom + unit * level
    sc.box("water", (0, 0, (bottom + top) / 2), (0.249, 0.179, max((top - bottom) / 2, 0.001)), WATER,
           show=level > 0)
    spill = s.overflow[fx]
    sc.box("spill", (0, -0.30, 0.9015), (min(0.12 + 0.03 * spill, 0.58), 0.07, 0.0015), WATER,
           show=spill > 0)

    # Mixer tap with separate hot (left, red) and cold (right, blue) handles.
    sc.add("tap.base", "cylinder", STEEL, (0.03, 0.015), pos=(0, 0.27, 0.915))
    sc.pipe("tap.column", (0, 0.27, 0.90), (0, 0.27, 1.12), 0.017, STEEL)
    sc.pipe("tap.spout", (0, 0.27, 1.12), (0.08, 0.06, 1.12), 0.014, STEEL)
    sc.pipe("tap.tip", (0.08, 0.06, 1.12), (0.08, 0.06, 1.09), 0.014, STEEL)
    aer = s.comps[f"aer.{fx}"]
    sc.add("aerator", "cylinder", BRASS, (0.016,), fromto=(0.08, 0.06, 1.072, 0.08, 0.06, 1.088))
    sc.anchors[aer.tag] = (0.08, 0.06, 1.08)
    sc.pipe("handle.hot", (-0.13, 0.27, 0.90), (-0.13, 0.27, 0.96), 0.012, HOT)
    sc.pipe("handle.cold", (0.13, 0.27, 0.90), (0.13, 0.27, 0.96), 0.012, COLD)

    # Flow on the last tick the tap ran: a weak flow is a broken trickle of
    # beads, a full one a solid column. Running both sides shows their sum.
    running = s.flow_tick == s.tick and fx in s.flow
    total = sum(s.flow.get(fx, {}).values()) if running else 0
    stream_rgba = (0.55, 0.78, 1.0, 0.85)
    sc.add("stream", "cylinder", stream_rgba, (0.0035 * max(total, 2),),
           fromto=(0.08, 0.06, 1.07, 0.08, 0.06, top + 0.002), show=total >= 2)
    sc.disc("splash", (0.08, 0.06, top + 0.003), 0.012 + 0.006 * total, (0.85, 0.93, 1.0, 0.9),
            show=total >= 2)
    for i in range(6):
        z = 1.06 - i * (1.06 - top) / 6
        sc.add(f"trickle{i}", "sphere", DRIP, (0.0048,), pos=(0.08, 0.06, z), show=total == 1)
    return sc


def _under_sink(s: State) -> Scene:
    fx = s.room
    sc = Scene(key=f"under:{fx}", camera_pos=(0.10, -1.02, 0.52), camera_target=(0.0, 0.10, 0.32))
    sc.box("floor", (0, 0, -0.01), (0.46, 0.31, 0.01), WOOD)
    sc.box("back", (0, 0.31, 0.36), (0.46, 0.01, 0.37), WALL)
    sc.box("left", (-0.46, 0, 0.36), (0.01, 0.31, 0.37), WOOD)
    sc.box("right", (0.46, 0, 0.36), (0.01, 0.31, 0.37), WOOD)
    sc.box("bowl.under", (0, 0.0, 0.67), (0.30, 0.21, 0.05), STEEL if fx == "kitchen" else CERAMIC)

    spots: dict[str, Vec] = {}
    # Supply: wall stub, wall-side joint, stop valve, tap-side joint, hose to the tap.
    for side, x, rgba in (("hot", -0.34, HOT), ("cold", 0.34, COLD)):
        jin, stop, jhose = f"jin.{fx}.{side}", f"stop.{fx}.{side}", f"jhose.{fx}.{side}"
        sc.pipe(f"{side}.stub", (x, 0.30, 0.16), (x, 0.20, 0.16), 0.011, rgba)
        sc.pipe(f"{side}.riser", (x, 0.20, 0.16), (x, 0.20, 0.335), 0.010, rgba)
        sc.pipe(f"{side}.hose", (x, 0.20, 0.35), (x * 0.18, 0.10, 0.62), 0.008, HOSE)
        for cid, at, axis, slide in ((jin, (x, 0.25, 0.16), "y", -0.05),
                                     (jhose, (x, 0.20, 0.345), "z", 0.05)):
            c = s.comps[cid]
            _nut(sc, cid, at, axis, 0.019, BRASS, c.open, slide)
            _drips(sc, s, cid, at)
            _outflow(sc, s, cid, at, spray=True)
            sc.anchors[c.tag] = at
            spots[cid] = at
        _valve(sc, s, stop, (x, 0.20, 0.25), 0.010)

    # Drain: tailpiece, slip joint, trap, slip joint, arm into the wall.
    jtail, trap, jarm = f"jtail.{fx}", f"trap.{fx}", f"jarm.{fx}"
    t, a = s.comps[trap], s.comps[jarm]
    sc.pipe("tailpiece", (-0.02, 0, 0.62), (-0.02, 0, 0.455), 0.021, PVC)
    sc.pipe("arm.up", (0.10, 0, 0.425), (0.10, 0, 0.46), 0.021, PVC)
    sc.pipe("arm.across", (0.10, 0, 0.46), (0.26, 0, 0.46), 0.021, PVC)
    sc.pipe("arm.wall", (0.26, 0, 0.46), (0.26, 0.30, 0.46), 0.021, PVC)
    sc.pipe("trap.in", (-0.02, 0, 0.43), (-0.02, 0, 0.30), 0.021, PVC, show=not t.open)
    sc.pipe("trap.bend", (-0.02, 0, 0.30), (0.10, 0, 0.30), 0.021, PVC, show=not t.open)
    sc.pipe("trap.out", (0.10, 0, 0.30), (0.10, 0, 0.40), 0.021, PVC, show=not t.open)
    # A removed trap lies on the floor; what is inside it shows at the bend.
    sc.pipe("loose.a", (-0.38, -0.24, 0.022), (-0.22, -0.24, 0.022), 0.021, PVC, show=t.open)
    sc.pipe("loose.b", (-0.38, -0.24, 0.022), (-0.38, -0.13, 0.022), 0.021, PVC, show=t.open)
    sc.pipe("loose.c", (-0.38, -0.13, 0.022), (-0.24, -0.13, 0.022), 0.021, PVC, show=t.open)
    sc.add("sludge", "sphere", SLUDGE, (0.03,), pos=(-0.38, -0.185, 0.035), show=t.open and bool(t.fault))
    sc.add("trap.hole1", "cylinder", DARK, (0.017, 0.002), pos=(-0.02, 0, 0.425), show=t.open)
    sc.add("trap.hole2", "cylinder", DARK, (0.017, 0.002), pos=(0.10, 0, 0.423), show=t.open)
    for cid, at in ((jtail, (-0.02, 0, 0.44)), (jarm, (0.10, 0, 0.41))):
        c = s.comps[cid]
        _nut(sc, cid, at, "z", 0.028, SLIP, c.open, -0.05 if cid == jtail else 0.05)
        _drips(sc, s, cid, at)
        _outflow(sc, s, cid, at, spray=False)
        sc.anchors[c.tag] = at
        spots[cid] = at
    sc.anchors[t.tag] = (-0.30, -0.24, 0.04) if t.open else (0.04, 0, 0.30)
    spots[trap] = (0.04, 0, 0.30)
    _outflow(sc, s, trap, (0.04, 0, 0.42), spray=False)

    for cid, at in spots.items():
        floor_at = (at[0], max(min(at[1], 0.22), -0.25), 0.0)
        _floor_marks(sc, s, cid, floor_at)
    _bucket(sc, s, {cid: (at[0], max(min(at[1], 0.19), -0.18), 0.0) for cid, at in spots.items()})
    return sc


def _utility(s: State) -> Scene:
    cold = s.manifold["cold"]
    sc = Scene(key="utility:" + ",".join(cold), camera_pos=(0.0, -2.05, 0.95),
               camera_target=(0.0, 0.2, 0.82))
    sc.box("floor", (0, 0, -0.01), (1.3, 0.5, 0.01), FLOOR)
    sc.box("wall", (0, 0.32, 0.85), (1.3, 0.02, 0.86), WALL)
    sc.box("ceiling", (0, 0.0, 1.66), (1.3, 0.5, 0.02), WALL)
    y = 0.20
    spots: dict[str, Vec] = {}

    # Main: up from the floor, through the meter, into the cold manifold.
    sc.pipe("main.rise", (-0.75, y, 0.0), (-0.75, y, 0.85), 0.014, COLD)
    sc.box("meter", (-0.75, y - 0.01, 0.60), (0.045, 0.035, 0.06), (0.20, 0.22, 0.25, 1))
    sc.add("meter.dial", "cylinder", (0.95, 0.95, 0.90, 1), (0.03, 0.002), pos=(-0.75, y - 0.047, 0.60),
           quat=(0.7071, 0.7071, 0, 0))
    _valve(sc, s, "main", (-0.75, y, 0.32), 0.014)
    sc.pipe("cold.header", (-0.75, y, 0.85), (0.0, y, 0.85), 0.014, COLD)

    # Cold branches: three outlets, one of them a capped spare.
    for i, cid in enumerate(cold):
        x = -0.52 + 0.20 * i
        if s.comps[cid].role == "spare":
            sc.pipe(f"cold.out{i}", (x, y, 0.85), (x, y, 1.24), 0.012, COLD)
            sc.add(f"cold.cap{i}", "cylinder", BRASS, (0.022, 0.02), pos=(x, y, 1.26))
        else:
            sc.pipe(f"cold.out{i}", (x, y, 0.85), (x, y, 1.65), 0.012, COLD)
            sc.add(f"cold.cap{i}", "cylinder", BRASS, (0.022, 0.02), pos=(x, y, 1.26), show=False)
        _valve(sc, s, cid, (x, y, 1.08), 0.012)

    # Heater feed, the water heater, and the hot manifold.
    sc.pipe("feed.rise", (0.0, y, 0.85), (0.0, y, 1.05), 0.013, COLD)
    _valve(sc, s, "heater", (0.0, y, 0.95), 0.013)
    sc.pipe("feed.across", (0.0, y, 1.05), (0.34, y, 1.05), 0.013, COLD)
    sc.pipe("feed.down", (0.34, y, 1.05), (0.34, y, 0.93), 0.013, COLD)
    sc.add("heater.tank", "cylinder", (0.92, 0.92, 0.90, 1), (0.16, 0.45), pos=(0.42, y + 0.01, 0.46))
    sc.add("heater.top", "cylinder", (0.80, 0.80, 0.78, 1), (0.16, 0.02), pos=(0.42, y + 0.01, 0.93))
    sc.pipe("hot.rise", (0.50, y, 0.93), (0.50, y, 1.28), 0.013, HOT)
    sc.pipe("hot.header", (0.50, y, 1.28), (0.12, y, 1.28), 0.013, HOT)
    for i, cid in enumerate(s.manifold["hot"]):
        x = 0.16 + 0.20 * i
        sc.pipe(f"hot.out{i}", (x, y, 1.28), (x, y, 1.65), 0.012, HOT)
        _valve(sc, s, cid, (x, y, 1.45), 0.012)

    # Drain branch from both fixtures, the cleanout plug, and the stack.
    co = s.comps["cleanout"]
    sc.pipe("stack", (0.95, y + 0.02, 0.0), (0.95, y + 0.02, 1.65), 0.05, DRAIN)
    sc.pipe("branch.in", (0.70, 0.31, 0.36), (0.70, 0.10, 0.36), 0.04, DRAIN)
    sc.pipe("branch.over", (0.70, 0.17, 0.36), (0.95, 0.17, 0.36), 0.04, DRAIN)
    at = (0.70, 0.04, 0.36)
    sc.add("cleanout.hub", "cylinder", DRAIN, (0.046,), fromto=(0.70, 0.10, 0.36, 0.70, 0.065, 0.36))
    sc.add("cleanout.plug", "cylinder", BRASS, (0.040,), fromto=(0.70, 0.066, 0.36, 0.70, 0.05, 0.36),
           show=not co.open)
    sc.box("cleanout.nut", (0.70, 0.045, 0.36), (0.014, 0.006, 0.014), BRASS, show=not co.open)
    sc.add("cleanout.hole", "cylinder", DARK, (0.034, 0.002), pos=(0.70, 0.064, 0.36),
           quat=(0.7071, 0.7071, 0, 0), show=co.open)
    sc.add("cleanout.sludge", "cylinder", SLUDGE, (0.030, 0.002), pos=(0.70, 0.062, 0.36),
           quat=(0.7071, 0.7071, 0, 0), show=co.open and bool(co.fault))
    sc.add("cleanout.loose", "cylinder", BRASS, (0.040, 0.008), pos=(0.52, -0.05, 0.008),
           show=co.open)
    _outflow(sc, s, "cleanout", (0.70, 0.04, 0.36), spray=False)
    sc.anchors[co.tag] = at
    spots["cleanout"] = (0.70, 0.02, 0.0)
    _floor_marks(sc, s, "cleanout", spots["cleanout"])
    _bucket(sc, s, spots)
    return sc


CLOSE_FOVY = 40.0


def _close_up(sc: Scene, tag: str) -> Scene:
    """Move the camera toward one tagged part, keeping the same line of sight.

    The shape list is unchanged, so the close-up shares its GL context with the
    full view; only the camera differs.
    """
    at, cam = sc.anchors[tag], sc.camera_pos
    d = [a - c for a, c in zip(at, cam)]
    dist = math.sqrt(sum(x * x for x in d))
    near = min(max(0.28 * dist, 0.22), 0.55)
    sc.camera_pos = tuple(a - x / dist * near for a, x in zip(at, d))
    sc.camera_target = at
    sc.fovy = CLOSE_FOVY
    return sc


def build(s: State, focus: str | None = None) -> Scene:
    """The current view, or with `focus` (a tag in view) a close-up of that part."""
    if s.room in FIXTURES:
        sc = _counter(s) if s.view == "counter" else _under_sink(s)
    else:
        sc = _utility(s)
    if focus is not None:
        if focus not in sc.anchors:
            raise ValueError(f"{focus} is not in the current view")
        _close_up(sc, focus)
    return sc
