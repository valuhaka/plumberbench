"""Level 5: what it adds, and that levels 1-4 did not move."""
import hashlib
import json

import pytest

from plumberbench import sim
from plumberbench.env import Episode
from plumberbench.generate import LEVELS, generate
from plumberbench.judge import score
from plumberbench.world import DIAGNOSES, LATE_MAX


def test_levels_1_to_4_are_the_houses_they_were():
    """Results and committed tasks for levels 1-4 stay valid: their houses are byte for byte unchanged."""
    h = hashlib.sha256()
    for lv in (1, 2, 3, 4):
        for seed in range(50):
            s = generate(seed, lv)
            h.update(json.dumps([s.faults, s.complaint, s.basin, s.manifold, s.budget, s.washers,
                                 {k: (c.tag, c.pos, c.fault, c.puddle, c.stain, c.wet_tick) for k, c in s.comps.items()},
                                 s.layout], sort_keys=True, default=str).encode())
    assert h.hexdigest() == "752cc156c114701e58c2a328e79b0c40cbc85db6c0c11a724843d5888e2a6f32"


def test_budget_washers_and_complaint_say_nothing_about_the_faults():
    houses = [generate(seed, 5) for seed in range(200)]
    assert {(s.budget, s.washers) for s in houses} == {(LEVELS[5]["budget"], LEVELS[5]["washers"])}
    assert len({len(s.faults) for s in houses}) >= 4
    words = ("drain", "leak", "block", "valve", "tap", "nozzle", "drip", "water", "weak", "grease")
    for s in houses:
        assert not any(w in s.complaint.lower() for w in words), s.complaint


def late_house():
    return generate(0, 5, faults=[{"type": "valve_not_open", "id": "stop.kitchen.cold", "pos": "closed"},
                                  {"type": "supply_leak", "id": "jhose.kitchen.cold", "cause": "worn", "late": 4}])


def test_a_late_washer_holds_until_its_valve_opens_then_gives_within_the_stated_time():
    s = late_house()
    s.room, s.view = "kitchen", "under_sink"
    stop, joint = s.comps["stop.kitchen.cold"], s.comps["jhose.kitchen.cold"]
    sim.apply(s, "wait", {"ticks": 10})
    assert joint.fault is None and s.damage == 0  # no pressure: nothing to see, nothing lost
    sim.apply(s, "set_valve", {"tag": stop.tag, "position": "open"})
    assert joint.fault is None
    sim.apply(s, "wait", {"ticks": LATE_MAX})
    assert joint.fault == "worn" and s.damage > 0


def test_finishing_before_a_late_washer_gives_is_not_a_repair_and_the_house_test_agrees():
    s = late_house()
    s.room, s.view = "kitchen", "under_sink"
    sim.apply(s, "set_valve", {"tag": s.comps["stop.kitchen.cold"].tag, "position": "open"})
    sim.apply(s, "finish", {"diagnosis": ["valve_not_open"]})
    r = score(s)
    assert r["faults_fixed"] == 1 and not r["clean"] and not r["functional_test"]["nothing drips"] and r["consistent"]


def test_refitting_a_weak_washer_before_it_gives_fixes_it():
    s = late_house()
    s.room, s.view = "kitchen", "under_sink"
    j = s.comps["jhose.kitchen.cold"].tag
    sim.apply(s, "open_joint", {"tag": j})
    sim.apply(s, "close_joint", {"tag": j})
    sim.apply(s, "set_valve", {"tag": s.comps["stop.kitchen.cold"].tag, "position": "open"})
    sim.apply(s, "wait", {"ticks": LATE_MAX})
    assert s.damage == 0 and all(score(s)["functional_test"].values())


def test_a_slow_trap_shows_only_with_both_taps():
    s = generate(0, 5, faults=[{"type": "trap_clog", "id": "trap.kitchen", "partial": True}])
    assert s.basin["kitchen"] == 0  # no standing water to give it away
    sim.apply(s, "run_tap", {"side": "cold", "ticks": 5})
    assert s.basin["kitchen"] == 0
    sim.apply(s, "run_tap", {"side": "both", "ticks": 3})
    assert s.basin["kitchen"] == 3
    r = score(s)
    assert not r["functional_test"]["kitchen keeps up with both taps"] and r["consistent"]


def test_the_main_is_seized_only_at_level_5():
    for level, refused in ((4, False), (5, True)):
        s = generate(1, level)
        s.room, s.view = "utility", "wall"
        main = s.comps["main"].tag
        if refused:
            with pytest.raises(sim.ActionError, match="seized"):
                sim.apply(s, "set_valve", {"tag": main, "position": "closed"})
        else:
            sim.apply(s, "set_valve", {"tag": main, "position": "closed"})


def test_at_level_5_inspect_shows_rather_than_tells_in_pictures_only_mode():
    faults = [{"type": "supply_leak", "id": "jhose.kitchen.cold", "cause": "loose"}]
    words, picture = Episode(0, 5, facts=True, render=False), Episode(0, 5, facts=False, render=False)
    for ep in (words, picture):
        ep.state = generate(0, 5, faults=faults)
        ep.act("look", view="under_sink")
    tag = words.state.comps["jhose.kitchen.cold"].tag
    said = words.act("inspect", tag=tag)
    assert "loose" in said.text
    told = picture.act("inspect", tag=tag).text
    assert "loose" not in told and "close-up shows" in told
    nut = next(f for f in said.facts if f["tag"] == tag)
    assert nut["nut"] == "backed off"  # what the close-up draws, for FACTS mode and the reference solver


def test_level_5_tells_no_drip_by_ear():
    ep = Episode(0, 5, facts=False, render=False)
    ep.state = generate(0, 5, faults=[{"type": "supply_leak", "id": "jhose.kitchen.cold", "cause": "worn"}])
    assert "Dripping" not in ep.act("wait", ticks=1).text


def test_every_level_5_diagnosis_word_is_a_known_fault_type():
    for seed in range(100):
        assert {f["type"] for f in generate(seed, 5).faults} <= set(DIAGNOSES)


def test_open_joint_tells_the_washer_at_level_5_only():
    for level, said in ((4, None), (5, "weak")):
        s = generate(0, level, faults=[{"type": "valve_not_open", "id": "stop.kitchen.cold", "pos": "closed"},
                                       {"type": "supply_leak", "id": "jhose.kitchen.cold", "cause": "worn",
                                        **({"late": 5} if level == 5 else {})}])
        s.room, s.view = "kitchen", "under_sink"
        text = sim.apply(s, "open_joint", {"tag": s.comps["jhose.kitchen.cold"].tag})
        assert (said in text) if said else ("washer" not in text)


def test_the_close_up_facts_come_only_with_inspect():
    s = generate(0, 5, faults=[{"type": "supply_leak", "id": "jhose.kitchen.cold", "cause": "loose"},
                               {"type": "aerator_clog", "id": "aer.kitchen"}])
    from plumberbench.observe import facts
    assert not any("scale" in f for f in facts(s))
    aer = s.comps["aer.kitchen"].tag
    sim.apply(s, "inspect", {"tag": aer})
    assert next(f for f in facts(s) if f.get("tag") == aer)["scale"] is True
    sim.apply(s, "look", {"view": "under_sink"})
    assert not any("nut" in f for f in facts(s))
    j = s.comps["jhose.kitchen.cold"].tag
    sim.apply(s, "inspect", {"tag": j})
    assert next(f for f in facts(s) if f.get("tag") == j)["nut"] == "backed off"


def test_level_5_houses_are_mopped_up():
    for seed in range(100):
        s = generate(seed, 5)
        assert all(v == 0 for v in s.basin.values()) and not any(c.puddle for c in s.comps.values())


@pytest.mark.parametrize("cid", ["jin.kitchen.cold", "jhose.kitchen.hot", "jtail.bathroom", "jarm.kitchen",
                                 "jin.bathroom.hot", "jin.bathroom.cold"])
def test_a_loose_nut_looks_different_from_a_tight_one_in_its_close_up(cid):
    """Fair only if a careful look can tell: the close-ups of the same joint, loose and worn,
    must differ clearly, with and without the bucket under it."""
    np = pytest.importorskip("numpy")
    try:
        from plumberbench.render import render_array
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no renderer: {e}")
    kind = "drain_leak" if cid.startswith(("jtail", "jarm")) else "supply_leak"
    for seed in (1, 2, 3):
        for bucket in (False, True):
            shots = []
            for cause in ("loose", "worn"):
                s = generate(seed, 5, faults=[{"type": kind, "id": cid, "cause": cause}])
                s.room, s.view = s.comps[cid].room, "under_sink"
                tag = s.comps[cid].tag
                if bucket:
                    sim.apply(s, "place_bucket", {"tag": tag})
                sim.apply(s, "inspect", {"tag": tag})
                shots.append(render_array(s, tag)[0][40:].astype(int))
            changed = (abs(shots[0] - shots[1]).sum(axis=2) > 60).sum()
            assert changed > 1500, (cid, seed, bucket, changed)
