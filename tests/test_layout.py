"""Pipe layouts under the sinks: varied, physically sound, and drawn as checked."""
from collections import Counter

import pytest

from plumberbench import generate as gen
from plumberbench import layout as L
from plumberbench.generate import generate
from plumberbench.scene import build
from plumberbench.world import FIXTURES

HOUSES = [(seed, level) for level in range(1, 5) for seed in range(100)]


def test_every_house_has_a_sound_layout_under_both_sinks():
    for seed, level in HOUSES:
        s = generate(seed, level)
        assert set(s.layout) == set(FIXTURES)
        for fx, lay in s.layout.items():
            assert L.clearance(lay) == [], (seed, level, fx, lay)


def test_layouts_vary_in_every_way_they_are_meant_to():
    modes, dirs, outer_hot, bottoms, heights = Counter(), Counter(), Counter(), [], []
    for seed, level in HOUSES:
        for lay in generate(seed, level).layout.values():
            m = L.mode(lay)
            modes[m] += 1
            dirs[lay["trap_dir"]] += 1
            if m.startswith("both"):
                outer_hot[abs(lay["hot_x"]) > abs(lay["cold_x"])] += 1
            bottoms.append(lay["trap_bottom"])
            heights.append(lay["hot_z"])
    assert set(modes) == {"split", "swapped", "both_left", "both_right"}
    assert min(modes.values()) > 50
    assert dirs[1] > 300 and dirs[-1] > 300
    assert outer_hot[True] > 50 and outer_hot[False] > 50
    assert max(bottoms) - min(bottoms) > 0.09 and max(heights) - min(heights) > 0.09
    a, b = generate(5, 2).layout, generate(6, 2).layout
    assert a != b and generate(5, 2).layout == a


def test_the_check_can_fail():
    """Each kind of impossibility is caught."""
    def problems(**change):
        return L.clearance({**L.DEFAULT, **change})
    assert problems() == []
    assert any("hot" in p and "cold" in p for p in problems(hot_x=0.30, cold_x=0.30))      # one through the other
    assert any("side wall" in p for p in problems(cold_x=0.43))                             # lever into the wall
    assert any("floor" in p for p in problems(trap_bottom=0.01))                            # trap through the floor
    # A low trap whose arm turns to the wall exactly where the cold riser stands.
    assert any("cold riser and drain arm_wall" in p
               for p in problems(cold_x=0.27, trap_w=0.13, arm_side=0.14, trap_bottom=0.22, leg=0.10, arm_rise=0.02))
    crossing = {**L.DEFAULT, "hot_x": -0.36, "cold_x": -0.24}
    assert L.supply(crossing, "hot")["hose"][1][0] < L.supply(crossing, "cold")["hose"][1][0], \
        "the line further left takes the left inlet, so hoses never cross"


def test_the_scene_draws_the_checked_geometry():
    for seed in range(20):
        s = generate(seed, 3)
        for fx in FIXTURES:
            s.room, s.view = fx, "under_sink"
            sc = build(s)
            lay = s.layout[fx]
            for side in ("hot", "cold"):
                p = L.supply(lay, side)
                assert sc.anchors[s.comps[f"jin.{fx}.{side}"].tag] == p["jin"]
                assert sc.anchors[s.comps[f"jhose.{fx}.{side}"].tag] == p["jhose"]
                assert sc.anchors[s.comps[f"stop.{fx}.{side}"].tag] == p["valve"]
            q = L.drain(lay)
            assert sc.anchors[s.comps[f"jtail.{fx}"].tag] == q["jtail"]
            assert sc.anchors[s.comps[f"jarm.{fx}"].tag] == q["jarm"]
            assert sc.anchors[s.comps[f"trap.{fx}"].tag] == q["trap_mid"]


def test_the_layout_never_changes_a_houses_faults(monkeypatch):
    """Layouts come from their own random stream, so seeds keep their faults and complaints."""
    real = [(generate(seed, level).faults, generate(seed, level).complaint) for seed, level in HOUSES[::9]]
    monkeypatch.setattr(gen.pipes, "sample", lambda rng: dict(L.DEFAULT))
    fixed = [(generate(seed, level).faults, generate(seed, level).complaint) for seed, level in HOUSES[::9]]
    assert real == fixed


@pytest.mark.parametrize("fixture", FIXTURES)
def test_bathroom_and_kitchen_look_different(fixture):
    s = generate(0, 1)
    s.room = fixture
    for view in ("counter", "under_sink"):
        s.view = view
        names = {g.name.split("#")[0] for g in build(s).shapes}
        if fixture == "bathroom" and view == "counter":
            assert {"lip.front", "grout.v1", "cupboard.handle.l"} <= names
        if fixture == "kitchen" and view == "counter":
            assert "grout.v1" not in names and "cabinet" in names
