"""The picture: built from state alone, the same every time, and showing what FACTS says."""
import hashlib

import pytest

from plumberbench import sim
from plumberbench.generate import generate
from plumberbench.observe import facts
from plumberbench.scene import HIDDEN_Z, build


def visible(sc):
    """Names of shapes on show (hidden ones are parked below the floor)."""
    out = set()
    for g in sc.shapes:
        z = g.fromto[2] if g.fromto else g.pos[2]
        if z > HIDDEN_Z + 1:
            out.add(g.name.split("#")[0])
    return out


def house(*faults):
    return generate(0, 1, faults=list(faults))


def test_every_tag_in_view_is_drawn_and_nothing_else():
    for seed in range(20):
        s = generate(seed, 4)
        for room, view in [("kitchen", "counter"), ("kitchen", "under_sink"),
                           ("bathroom", "counter"), ("bathroom", "under_sink"), ("utility", "wall")]:
            s.room, s.view = room, view
            assert set(build(s).anchors) == {c.tag for c in s.in_view()}


def test_shape_list_length_is_fixed_per_view():
    """The renderer reuses one GL context per view, so shape counts must not change."""
    for room, view in [("kitchen", "counter"), ("kitchen", "under_sink"), ("utility", "wall")]:
        counts = set()
        for seed in range(30):
            s = generate(seed, 1 + seed % 4)
            s.room, s.view = room, view
            counts.add(len(build(s).shapes))
            s.comps[f"trap.{'kitchen'}"].open = True
            s.bucket_at, s.bucket_fill = "trap.kitchen", 5
            counts.add(len(build(s).shapes))
        assert len(counts) == 1, (room, view, counts)


def test_valve_lever_shows_position():
    s = house({"type": "valve_not_open", "id": "stop.kitchen.cold", "pos": "closed"})
    s.view = "under_sink"
    lever = next(g for g in build(s).shapes if g.name.startswith("stop.kitchen.cold.lever#"))
    x0, _, z0, x1, _, z1 = lever.fromto
    assert abs(z1 - z0) < 1e-9 and abs(x1 - x0) > 0.05, "closed: across the pipe"
    s.comps["stop.kitchen.cold"].pos = "open"
    lever = next(g for g in build(s).shapes if g.name.startswith("stop.kitchen.cold.lever#"))
    x0, _, z0, x1, _, z1 = lever.fromto
    assert abs(x1 - x0) < 1e-9 and z1 - z0 > 0.05, "open: along the pipe"


def test_picture_matches_facts_for_drips_puddles_stains_and_traps():
    s = house({"type": "supply_leak", "id": "jhose.kitchen.cold", "cause": "worn"},
              {"type": "trap_clog", "id": "trap.kitchen"})
    s.comps["jtail.kitchen"].stain = True
    sim.apply(s, "look", {"view": "under_sink"})
    shown = visible(build(s))
    for f in facts(s):
        if f.get("type") != "joint":
            continue
        cid = next(c.id for c in s.comps.values() if c.tag == f["tag"])
        assert (f"{cid}.drip0" in shown) == f["wet"], cid
        assert (f"{cid}.puddle" in shown) == (f["puddle"] > 0), cid
        assert (f"{cid}.stain" in shown) == f["stain"], cid
    assert "trap.bend" in shown and "sludge" not in shown
    sim.apply(s, "open_joint", {"tag": s.comps["trap.kitchen"].tag})
    shown = visible(build(s))
    assert "trap.bend" not in shown and "sludge" in shown


def test_weak_and_full_flow_look_different():
    s = house({"type": "aerator_clog", "id": "aer.kitchen"})
    sim.apply(s, "run_tap", {"side": "cold", "ticks": 1})
    assert "trickle0" in visible(build(s)) and "stream" not in visible(build(s))
    s = house({"type": "aerator_clog", "id": "aer.bathroom"})
    sim.apply(s, "run_tap", {"side": "cold", "ticks": 1})
    assert "stream" in visible(build(s)) and "trickle0" not in visible(build(s))
    sim.apply(s, "wait", {"ticks": 1})
    assert "stream" not in visible(build(s)), "the stream shows only on the tick the tap ran"


# ----------------------------------------------------------- real pixels

@pytest.fixture(scope="module")
def render():
    try:
        from plumberbench.render import render_array
        render_array(generate(0, 1))
    except Exception as e:  # no EGL on this machine
        pytest.skip(f"no headless GL: {e}")
    return render_array


def digest(a):
    return hashlib.sha256(a.tobytes()).hexdigest()


def test_render_is_deterministic_and_reuse_is_invisible(render):
    import plumberbench.render as r
    a = generate(5, 3)
    b = generate(6, 3)
    b.room = a.room = "kitchen"
    a.view = b.view = "under_sink"
    first = digest(render(a))
    render(b)                       # same view, different house, reusing the GL context
    again = digest(render(a))
    r._cache.clear()
    fresh = digest(render(a))       # compiled from scratch
    assert first == again == fresh


def test_status_stamp_changes_the_picture(render):
    s = generate(0, 1)
    before = render(s)
    sim.apply(s, "look", {"view": "counter"})  # step +1, nothing else changes
    after = render(s)
    assert digest(before[40:]) == digest(after[40:]), "below the stamp the view is unchanged"
    assert digest(before[:30]) != digest(after[:30]), "the stamp shows the new step"
