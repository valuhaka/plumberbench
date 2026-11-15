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

from . import layout as pipes
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
PORCELAIN: RGBA = (0.97, 0.97, 0.96, 1)
VANITY: RGBA = (0.95, 0.95, 0.94, 1)
CUPBOARD: RGBA = (0.93, 0.93, 0.91, 1)
TILE: RGBA = (0.84, 0.85, 0.86, 1)
GROUT: RGBA = (0.69, 0.71, 0.73, 1)
HANDLE: RGBA = (0.55, 0.57, 0.60, 1)
BATH_FLOOR: RGBA = (0.76, 0.77, 0.78, 1)
CHROME: RGBA = (0.80, 0.82, 0.86, 1)
CHROME_NUT: RGBA = (0.62, 0.64, 0.68, 1)
LEVER: RGBA = (0.08, 0.08, 0.09, 1)
THREAD: RGBA = (0.62, 0.52, 0.26, 1)
SCALE: RGBA = (0.95, 0.95, 0.88, 1)

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
    close_from: dict[str, Vec] = field(default_factory=dict)  # tag -> camera for its close-up, if not the usual
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


def _nut(sc: Scene, name: str, at: Vec, axis: str, r: float, rgba: RGBA, undone: bool, slide: float,
         loose: bool = False):
    """A joint's nut, slid away along the pipe when undone, with the seam showing. A loose nut
    (drawn at level 5, where `inspect` no longer says it in words) is backed off a little,
    with bare thread showing between it and the fitting."""
    back = 0.016 * (1 if slide > 0 else -1)
    centre = _axis_offset(at, axis, slide) if undone else _axis_offset(at, axis, back) if loose else at
    sc.add(name, "cylinder", rgba, (r,),
           fromto=(*_axis_offset(centre, axis, -0.013), *_axis_offset(centre, axis, 0.013)))
    sc.add(name + ".seam", "cylinder", DARK, (r - 0.004,),
           fromto=(*_axis_offset(at, axis, -0.005), *_axis_offset(at, axis, 0.005)), show=undone)
    bare = loose and not undone  # always in the shape list, so the GL model is reused
    sc.add(name + ".thread", "cylinder", THREAD, (r * 0.78,),
           fromto=(*_axis_offset(at, axis, -0.013), *_axis_offset(at, axis, 0.013)), show=bare)
    for k in range(4):
        ring = _axis_offset(at, axis, -0.011 + k * 0.0075)
        sc.add(f"{name}.thread{k}", "cylinder", DARK, (r * 0.80,),
               fromto=(*_axis_offset(ring, axis, -0.0012), *_axis_offset(ring, axis, 0.0012)), show=bare)


def _nut_at(at: Vec, axis: str, slide: float) -> Vec:
    """Where a loose nut drawn backed off sits (the label goes on the nut, not the thread)."""
    return _axis_offset(at, axis, 0.016 * (1 if slide > 0 else -1))


def _scale(sc: Scene, s: State, aer, tip: Vec, r: float):
    """Level 5: in the close-up of a blocked aerator it is crusted with white scale, since
    `inspect` no longer says so in words."""
    show = s.level >= 5 and s.inspected == aer.id and bool(aer.fault)
    x, y, z = tip
    sc.add("aerator.scale", "cylinder", SCALE, (r * 1.18,), fromto=(x, y, z - 0.004, x, y, z + 0.003), show=show)
    for k, (dx, dy) in enumerate(((0.6, 0.2), (-0.5, 0.5), (0.1, -0.7), (-0.4, -0.4))):
        sc.add(f"aerator.scale{k}", "sphere", SCALE, (r * 0.32,), pos=(x + dx * r, y + dy * r, z - 0.006), show=show)


def _lever(sc: Scene, name: str, stem: Vec, pos: str, toward: float = 1.0):
    """Quarter-turn lever facing the camera (-y), pivoting in the x-z plane.

    Open: points up along the pipe. Closed: points across it, toward `toward`
    (+1 right, -1 left). Half: 45 degrees. Geometry from layout.lever.
    """
    front, tip = pipes.lever(stem, toward, pos)
    sc.add(name + ".stem", "cylinder", STEEL, (0.006,), fromto=(*stem, *front))
    sc.add(name, "capsule", LEVER, (pipes.R_LEVER,), fromto=(*front, *tip))


def _valve(sc: Scene, s: State, cid: str, at: Vec, pipe_r: float, toward: float = 1.0):
    c = s.comps[cid]
    sc.add(cid + ".body", "cylinder", BRASS, (pipe_r + 0.013,),
           fromto=(at[0], at[1], at[2] - 0.022, at[0], at[1], at[2] + 0.022))
    _lever(sc, cid + ".lever", at, c.pos, toward)
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

GAUGE_UNIT = 0.027   # height of one unit of water in a basin


def _basin(sc: Scene, s: State, half_x: float, half_y: float, bottom: float, rim: float, rgba: RGBA) -> float:
    """Bowl, plughole, numbered level marks on its back wall, standing water and spills.

    Returns the height of the water surface.
    """
    fx = s.room
    mid, half = (bottom + rim) / 2, (rim - bottom) / 2
    sc.box("bowl.bottom", (0, 0, bottom - 0.01), (half_x, half_y, 0.01), rgba)
    sc.box("bowl.front", (0, -half_y + 0.005, mid), (half_x, 0.005, half), rgba)
    sc.box("bowl.back", (0, half_y - 0.005, mid), (half_x, 0.005, half), rgba)
    sc.box("bowl.left", (-half_x + 0.005, 0, mid), (0.005, half_y, half), rgba)
    sc.box("bowl.right", (half_x - 0.005, 0, mid), (0.005, half_y, half), rgba)
    sc.disc("plughole", (0, 0, bottom + 0.0005), 0.03, DARK)
    face = half_y - 0.0115
    for k in range(1, BASIN_CAP + 1):
        z = bottom + GAUGE_UNIT * k
        sc.box(f"mark{k}", (-0.12, face, z), (0.05 if k % 4 else 0.08, 0.001, 0.0022), MARK)
        sc.notes[str(k)] = (-0.045, face - 0.0005, z)
    level = s.basin[fx]
    top = bottom + GAUGE_UNIT * level
    sc.box("water", (0, 0, (bottom + top) / 2),
           (half_x - 0.011, half_y - 0.011, max((top - bottom) / 2, 0.001)), WATER, show=level > 0)
    spill = s.overflow[fx]
    sc.box("spill", (0, -half_y - 0.11, rim + 0.0015), (min(0.12 + 0.03 * spill, 0.58), 0.07, 0.0015), WATER,
           show=spill > 0)
    return top


def _stream(sc: Scene, s: State, tip: Vec, top: float) -> None:
    """Flow on the last tick the tap ran: a weak flow is a broken trickle of
    beads, a full one a solid column. Running both sides shows their sum."""
    fx = s.room
    running = s.flow_tick == s.tick and fx in s.flow
    total = sum(s.flow.get(fx, {}).values()) if running else 0
    x, y, z = tip
    sc.add("stream", "cylinder", (0.55, 0.78, 1.0, 0.85), (0.0035 * max(total, 2),),
           fromto=(x, y, z, x, y, top + 0.002), show=total >= 2)
    sc.disc("splash", (x, y, top + 0.003), 0.012 + 0.006 * total, (0.85, 0.93, 1.0, 0.9), show=total >= 2)
    for i in range(6):
        sc.add(f"trickle{i}", "sphere", DRIP, (0.0048,), pos=(x, y, z - 0.01 - i * (z - 0.01 - top) / 6),
               show=total == 1)


def _worktop(sc: Scene, half_x: float, half_y: float, rgba: RGBA) -> None:
    """A worktop 1.24 m wide and 0.78 m deep with a hole for the bowl."""
    depth = (0.39 - half_y) / 2
    sc.box("top.front", (0, -0.39 + depth, 0.885), (0.62, depth, 0.015), rgba)
    sc.box("top.back", (0, 0.39 - depth, 0.885), (0.62, depth, 0.015), rgba)
    side = (0.62 - half_x) / 2
    sc.box("top.left", (-0.62 + side, 0, 0.885), (side, half_y, 0.015), rgba)
    sc.box("top.right", (0.62 - side, 0, 0.885), (side, half_y, 0.015), rgba)


def _counter_kitchen(s: State) -> Scene:
    """Steel sink in a dark worktop over a wooden cupboard; a tall mixer with a swan neck."""
    fx = s.room
    sc = Scene(key=f"counter:{fx}", camera_pos=(0.0, -0.78, 1.30), camera_target=(0.0, 0.10, 0.80))
    sc.box("floor", (0, -0.6, -0.01), (1.2, 1.0, 0.01), FLOOR)
    sc.box("cabinet", (0, -0.385, 0.435), (0.62, 0.005, 0.435), WOOD)
    sc.box("wall", (0, 0.40, 1.0), (0.9, 0.02, 0.6), WALL)
    _worktop(sc, 0.26, 0.19, COUNTER)
    top = _basin(sc, s, 0.26, 0.19, 0.66, 0.90, STEEL)

    # Mixer tap with separate hot (left, red) and cold (right, blue) handles.
    sc.add("tap.base", "cylinder", STEEL, (0.03, 0.015), pos=(0, 0.27, 0.915))
    sc.pipe("tap.column", (0, 0.27, 0.90), (0, 0.27, 1.12), 0.017, STEEL)
    sc.pipe("tap.spout", (0, 0.27, 1.12), (0.08, 0.06, 1.12), 0.014, STEEL)
    sc.pipe("tap.tip", (0.08, 0.06, 1.12), (0.08, 0.06, 1.09), 0.014, STEEL)
    aer = s.comps[f"aer.{fx}"]
    sc.add("aerator", "cylinder", BRASS, (0.016,), fromto=(0.08, 0.06, 1.072, 0.08, 0.06, 1.088))
    _scale(sc, s, aer, (0.08, 0.06, 1.072), 0.016)
    sc.anchors[aer.tag] = (0.08, 0.06, 1.08)
    sc.pipe("handle.hot", (-0.13, 0.27, 0.90), (-0.13, 0.27, 0.96), 0.012, HOT)
    sc.pipe("handle.cold", (0.13, 0.27, 0.90), (0.13, 0.27, 0.96), 0.012, COLD)
    _stream(sc, s, (0.08, 0.06, 1.07), top)
    return sc


def _counter_bathroom(s: State) -> Scene:
    """White porcelain basin in a white vanity, light grey tiles; a short basin mixer.

    The camera looks down more steeply than in the kitchen: the bowl is shallower
    front to back, and every level mark must stay in view above the front lip.
    """
    fx = s.room
    sc = Scene(key=f"counter:{fx}", camera_pos=(0.0, -0.56, 1.42), camera_target=(0.0, 0.10, 0.78))
    sc.box("floor", (0, -0.6, -0.01), (1.2, 1.0, 0.01), BATH_FLOOR)
    # The cupboard under the basin: two white doors with small handles.
    sc.box("cupboard", (0, -0.385, 0.435), (0.62, 0.005, 0.435), CUPBOARD)
    sc.box("cupboard.seam", (0, -0.3915, 0.44), (0.0015, 0.0015, 0.40), GROUT)
    sc.pipe("cupboard.handle.l", (-0.05, -0.405, 0.70), (-0.05, -0.405, 0.78), 0.006, HANDLE)
    sc.pipe("cupboard.handle.r", (0.05, -0.405, 0.70), (0.05, -0.405, 0.78), 0.006, HANDLE)
    # The wall: light grey tiles, 15 cm square, with grout lines.
    sc.box("wall", (0, 0.40, 1.0), (0.9, 0.02, 0.6), TILE)
    for i in range(1, 12):
        sc.box(f"grout.v{i}", (-0.9 + 0.15 * i, 0.3785, 1.25), (0.0015, 0.0015, 0.36), GROUT)
    for i in range(1, 5):
        sc.box(f"grout.h{i}", (0, 0.3785, 0.9 + 0.15 * i), (0.9, 0.0015, 0.0015), GROUT)
    _worktop(sc, 0.22, 0.16, VANITY)
    top = _basin(sc, s, 0.22, 0.16, 0.66, 0.90, PORCELAIN)
    # A rolled porcelain lip around the bowl.
    for name, a, b in (("lip.front", (-0.22, -0.16, 0.9), (0.22, -0.16, 0.9)),
                       ("lip.back", (-0.22, 0.16, 0.9), (0.22, 0.16, 0.9)),
                       ("lip.left", (-0.22, -0.16, 0.9), (-0.22, 0.16, 0.9)),
                       ("lip.right", (0.22, -0.16, 0.9), (0.22, 0.16, 0.9))):
        sc.pipe(name, a, b, 0.013, PORCELAIN)

    # Basin mixer: a short column and spout; hot (left, red) and cold (right, blue) handles.
    sc.add("tap.base", "cylinder", STEEL, (0.026, 0.008), pos=(0, 0.25, 0.908))
    sc.pipe("tap.column", (0, 0.25, 0.905), (0, 0.25, 1.00), 0.016, STEEL)
    sc.pipe("tap.spout", (0, 0.25, 1.00), (0, 0.10, 0.978), 0.012, STEEL)
    aer = s.comps[f"aer.{fx}"]
    sc.add("aerator", "cylinder", BRASS, (0.013,), fromto=(0, 0.10, 0.958, 0, 0.10, 0.972))
    _scale(sc, s, aer, (0, 0.10, 0.958), 0.013)
    sc.anchors[aer.tag] = (0, 0.10, 0.965)
    for side, x, rgba in (("hot", -0.10, HOT), ("cold", 0.10, COLD)):
        sc.pipe(f"handle.{side}.stem", (x, 0.25, 0.90), (x, 0.25, 0.94), 0.009, STEEL)
        sc.pipe(f"handle.{side}", (x - 0.025, 0.25, 0.945), (x + 0.025, 0.25, 0.945), 0.008, STEEL)
        sc.add(f"handle.{side}.cap", "sphere", rgba, (0.010,), pos=(x, 0.25, 0.955))
    _stream(sc, s, (0, 0.10, 0.956), top)
    return sc


def _under_sink(s: State) -> Scene:
    """Inside the cupboard. Where the pipes run comes from the house's layout (layout.py)."""
    fx = s.room
    lay = s.layout.get(fx) or pipes.DEFAULT
    bath = fx == "bathroom"
    shell, back = (CUPBOARD, CUPBOARD) if bath else (WOOD, WALL)
    drain_rgba, nut_rgba = (CHROME, CHROME_NUT) if bath else (PVC, SLIP)
    sc = Scene(key=f"under:{fx}", camera_pos=(0.10, -1.02, 0.52), camera_target=(0.0, 0.10, 0.32))
    sc.box("floor", (0, 0, -0.01), (0.46, 0.31, 0.01), shell)
    sc.box("back", (0, 0.31, 0.36), (0.46, 0.01, 0.37), back)
    sc.box("left", (-0.46, 0, 0.36), (0.01, 0.31, 0.37), shell)
    sc.box("right", (0.46, 0, 0.36), (0.01, 0.31, 0.37), shell)
    sc.box("bowl.under", (0, 0.0, 0.67), (0.30, 0.21, 0.05), PORCELAIN if bath else STEEL)

    spots: dict[str, Vec] = {}
    # Supply: wall stub, wall-side joint, stop valve, tap-side joint, hose to the tap.
    for side, rgba in (("hot", HOT), ("cold", COLD)):
        p = pipes.supply(lay, side)
        jin, stop, jhose = f"jin.{fx}.{side}", f"stop.{fx}.{side}", f"jhose.{fx}.{side}"
        sc.pipe(f"{side}.stub", *p["stub"], pipes.R_SUPPLY, rgba)
        sc.pipe(f"{side}.riser", *p["riser"], 0.010, rgba)
        sc.pipe(f"{side}.hose", *p["hose"], pipes.R_HOSE, HOSE)
        for cid, at, axis, slide in ((jin, p["jin"], "y", -0.05), (jhose, p["jhose"], "z", 0.05)):
            c = s.comps[cid]
            shown = s.level >= 5 and s.inspected == cid  # level 5: found by looking closely
            loose = shown and c.fault == "loose"
            _nut(sc, cid, at, axis, pipes.R_NUT, BRASS, c.open, slide, loose=loose)
            _drips(sc, s, cid, at)
            _outflow(sc, s, cid, at, spray=True)
            sc.anchors[c.tag] = _nut_at(at, axis, slide) if loose else at
            if shown and cid == jin:  # seen end-on from the front: look at it from the side instead
                other = pipes.supply(lay, "cold" if side == "hot" else "hot")["jin"]
                # Away from the other supply if it comes out on the same side, else from the middle.
                way = (1 if at[0] > other[0] else -1) if abs(other[0] - at[0]) < 0.25 else (1 if at[0] < 0 else -1)
                sc.close_from[c.tag] = (max(-0.42, min(0.42, at[0] + 0.20 * way)), at[1] - 0.10, at[2] + 0.06)
            spots[cid] = at
        _valve(sc, s, stop, p["valve"], 0.010, p["toward"])

    # Drain: tailpiece, slip joint, trap, slip joint, arm into the wall.
    q = pipes.drain(lay)
    jtail, trap, jarm = f"jtail.{fx}", f"trap.{fx}", f"jarm.{fx}"
    t = s.comps[trap]
    r = pipes.R_DRAIN
    sc.pipe("tailpiece", *q["tail"], r, drain_rgba)
    sc.pipe("arm.up", *q["arm_up"], r, drain_rgba)
    sc.pipe("arm.side", *q["arm_side"], r, drain_rgba)
    sc.pipe("arm.wall", *q["arm_wall"], r, drain_rgba)
    sc.pipe("trap.in", *q["trap_in"], r, drain_rgba, show=not t.open)
    sc.pipe("trap.bend", *q["bend"], r, drain_rgba, show=not t.open)
    sc.pipe("trap.out", *q["trap_out"], r, drain_rgba, show=not t.open)
    # A removed trap lies on the floor; what is inside it shows at the bend.
    sc.pipe("loose.a", (-0.38, -0.24, 0.022), (-0.22, -0.24, 0.022), r, drain_rgba, show=t.open)
    sc.pipe("loose.b", (-0.38, -0.24, 0.022), (-0.38, -0.13, 0.022), r, drain_rgba, show=t.open)
    sc.pipe("loose.c", (-0.38, -0.13, 0.022), (-0.24, -0.13, 0.022), r, drain_rgba, show=t.open)
    sc.add("sludge", "sphere", SLUDGE, (0.03,), pos=(-0.38, -0.185, 0.035), show=t.open and bool(t.fault))
    sc.add("trap.hole1", "cylinder", DARK, (0.017, 0.002), pos=q["hole_in"], show=t.open)
    sc.add("trap.hole2", "cylinder", DARK, (0.017, 0.002), pos=q["hole_out"], show=t.open)
    for cid, at, slide in ((jtail, q["jtail"], -0.05), (jarm, q["jarm"], 0.05)):
        c = s.comps[cid]
        loose = s.level >= 5 and s.inspected == cid and c.fault == "loose"
        _nut(sc, cid, at, "z", pipes.R_SLIP, nut_rgba, c.open, slide, loose=loose)
        _drips(sc, s, cid, at)
        _outflow(sc, s, cid, at, spray=False)
        sc.anchors[c.tag] = _nut_at(at, "z", slide) if loose else at
        spots[cid] = at
    sc.anchors[t.tag] = (-0.30, -0.24, 0.04) if t.open else q["trap_mid"]
    spots[trap] = q["trap_mid"]
    _outflow(sc, s, trap, (0.0, 0.0, q["hole_in"][2] - 0.01), spray=False)

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
    if tag in sc.close_from:  # a part that the line of sight shows end-on: seen from the side
        sc.camera_pos, sc.camera_target, sc.fovy = sc.close_from[tag], at, CLOSE_FOVY
        return sc
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
        if s.view == "under_sink":
            sc = _under_sink(s)
        else:
            sc = _counter_bathroom(s) if s.room == "bathroom" else _counter_kitchen(s)
    else:
        sc = _utility(s)
    if focus is not None:
        if focus not in sc.anchors:
            raise ValueError(f"{focus} is not in the current view")
        _close_up(sc, focus)
    return sc
