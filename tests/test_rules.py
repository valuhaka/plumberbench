"""The rules of the world, one behaviour per test."""
import dataclasses

import pytest

from plumberbench import sim
from plumberbench.generate import generate
from plumberbench.sim import ActionError, apply
from plumberbench.world import BASIN_CAP, SPRAY_RATE


def house(*faults, level=1):
    return generate(0, level, faults=list(faults) or [{"type": "aerator_clog", "id": "aer.bathroom"}])


def tag(s, cid):
    return s.comps[cid].tag


def flows(s, fx="kitchen"):
    f = sim.supply(s)
    return f[(fx, "cold")], f[(fx, "hot")]


def test_same_seed_same_house():
    a, b = generate(7, 3), generate(7, 3)
    assert dataclasses.asdict(a) == dataclasses.asdict(b)
    assert dataclasses.asdict(a) != dataclasses.asdict(generate(8, 3))


def test_valves_set_flow_per_side():
    s = house()
    assert flows(s) == (2, 2)
    s.comps["stop.kitchen.cold"].pos = "half"
    assert flows(s) == (1, 2)
    s.comps["heater"].pos = "closed"
    assert flows(s) == (1, 0)
    assert flows(s, "bathroom")[1] == 0, "the heater valve feeds hot water everywhere"
    s.comps["main"].pos = "closed"
    assert flows(s) == (0, 0)


def test_clogged_aerator_weakens_both_sides():
    s = house({"type": "aerator_clog", "id": "aer.kitchen"})
    assert flows(s) == (1, 1)
    assert flows(s, "bathroom") == (2, 2)


def test_supply_leak_runs_until_pressure_is_off():
    s = house({"type": "supply_leak", "id": "jhose.kitchen.cold", "cause": "worn"})
    apply(s, "wait", {"ticks": 3})
    assert s.damage == 3
    apply(s, "look", {"view": "under_sink"})
    apply(s, "set_valve", {"tag": tag(s, "stop.kitchen.cold"), "position": "closed"})
    apply(s, "wait", {"ticks": 3})
    assert s.damage == 3, "a closed stop valve takes pressure off the joint beyond it"


def test_bucket_catches_a_leak_until_it_is_full():
    s = house({"type": "supply_leak", "id": "jin.kitchen.hot", "cause": "worn"})
    apply(s, "place_bucket", {"tag": tag(s, "jin.kitchen.hot")})  # one tick, one drip caught
    apply(s, "wait", {"ticks": 9})
    assert (s.damage, s.bucket_fill) == (0, 10)
    apply(s, "wait", {"ticks": 2})
    assert s.damage == 2, "a full bucket overflows"


def test_undoing_a_joint_under_pressure_sprays():
    s = house()
    apply(s, "open_joint", {"tag": tag(s, "jhose.kitchen.hot")})
    assert s.damage == SPRAY_RATE * 3
    assert flows(s)[1] == 0


def test_clear_drain_empties_and_clogged_drain_fills():
    s = house()
    apply(s, "run_tap", {"side": "both", "ticks": 3})
    assert s.basin["kitchen"] == 0
    s = house({"type": "trap_clog", "id": "trap.kitchen"})
    before = s.basin["kitchen"]
    apply(s, "run_tap", {"side": "cold", "ticks": 2})
    assert s.basin["kitchen"] == before + 2


def test_basin_overflow_is_damage():
    s = house({"type": "trap_clog", "id": "trap.kitchen"})
    s.basin["kitchen"] = BASIN_CAP
    apply(s, "run_tap", {"side": "both", "ticks": 2})
    assert s.basin["kitchen"] == BASIN_CAP and s.damage == 4


def test_removing_a_trap_spills_unless_a_bucket_is_under_it():
    wet = house({"type": "trap_clog", "id": "trap.kitchen"})
    level = wet.basin["kitchen"]
    apply(wet, "open_joint", {"tag": tag(wet, "trap.kitchen")})
    assert wet.damage == level + 1 and wet.basin["kitchen"] == 0
    dry = house({"type": "trap_clog", "id": "trap.kitchen"})
    apply(dry, "place_bucket", {"tag": tag(dry, "trap.kitchen")})
    apply(dry, "open_joint", {"tag": tag(dry, "trap.kitchen")})
    assert dry.damage == 0 and dry.bucket_fill == level + 1


def test_branch_clog_blocks_both_basins_and_empties_at_the_cleanout():
    s = house({"type": "branch_clog", "id": "cleanout"})
    total = s.basin["kitchen"] + s.basin["bathroom"]
    apply(s, "go", {"room": "utility"})
    assert "full of water" in apply(s, "inspect", {"tag": tag(s, "cleanout")})
    apply(s, "place_bucket", {"tag": tag(s, "cleanout")})
    apply(s, "open_joint", {"tag": tag(s, "cleanout")})
    assert s.bucket_fill == total and s.damage == 0


def test_cleanout_sounds_hollow_when_the_blockage_is_in_a_trap():
    s = house({"type": "trap_clog", "id": "trap.kitchen"})
    apply(s, "go", {"room": "utility"})
    assert "hollow" in apply(s, "inspect", {"tag": tag(s, "cleanout")})


def test_a_clog_hides_a_leak_below_it():
    s = house({"type": "trap_clog", "id": "trap.kitchen"},
              {"type": "drain_leak", "id": "jarm.kitchen", "cause": "worn"})
    apply(s, "run_tap", {"side": "cold", "ticks": 2})
    assert s.comps["jarm.kitchen"].puddle == 0, "no water reaches the joint past the clog"
    s.comps["trap.kitchen"].fault = None
    apply(s, "wait", {"ticks": 1})
    assert s.comps["jarm.kitchen"].puddle == 1


def test_leak_above_a_clog_drips_while_water_stands():
    s = house({"type": "trap_clog", "id": "trap.kitchen"},
              {"type": "drain_leak", "id": "jtail.kitchen", "cause": "loose"})
    apply(s, "wait", {"ticks": 2})
    assert s.damage == 2


def test_tightening_fixes_loose_but_not_worn():
    s = house({"type": "supply_leak", "id": "jin.kitchen.cold", "cause": "loose"})
    apply(s, "repair", {"tag": tag(s, "jin.kitchen.cold"), "method": "tighten"})
    assert s.comps["jin.kitchen.cold"].fault is None
    s = house({"type": "supply_leak", "id": "jin.kitchen.cold", "cause": "worn"})
    apply(s, "repair", {"tag": tag(s, "jin.kitchen.cold"), "method": "tighten"})
    assert s.comps["jin.kitchen.cold"].fault == "worn"


def test_forcing_a_sound_joint_damages_it():
    s = house()
    msg = apply(s, "repair", {"tag": tag(s, "jtail.kitchen"), "method": "tighten"})
    assert "washer give" in msg and s.comps["jtail.kitchen"].fault == "worn"


def test_refit_uses_a_washer_and_mends_the_joint():
    s = house({"type": "drain_leak", "id": "jarm.kitchen", "cause": "worn"})
    t = tag(s, "jarm.kitchen")
    apply(s, "open_joint", {"tag": t})
    apply(s, "close_joint", {"tag": t})
    assert s.washers == 1 and s.comps["jarm.kitchen"].fault is None
    apply(s, "open_joint", {"tag": t})
    apply(s, "close_joint", {"tag": t})
    apply(s, "open_joint", {"tag": t})
    with pytest.raises(ActionError, match="no washers"):
        apply(s, "close_joint", {"tag": t})


def test_impossible_actions_cost_nothing():
    s = house()
    before = dataclasses.asdict(s)
    for tool, args in [
        ("go", {"room": "kitchen"}), ("go", {"room": "attic"}), ("look", {"view": "wall"}),
        ("inspect", {"tag": "Z9"}), ("inspect", {"tag": tag(s, "main")}),
        ("set_valve", {"tag": tag(s, "trap.kitchen"), "position": "open"}),
        ("set_valve", {"tag": tag(s, "stop.kitchen.hot"), "position": "open"}),
        ("close_joint", {"tag": tag(s, "trap.kitchen")}),
        ("repair", {"tag": tag(s, "trap.kitchen"), "method": "clear"}),
        ("run_tap", {"side": "warm", "ticks": 1}), ("run_tap", {"side": "hot", "ticks": 99}),
        ("finish", {"diagnosis": ["gremlins"]}), ("fly", {}), ("wait", {}),
    ]:
        with pytest.raises(ActionError):
            apply(s, tool, args)
    assert dataclasses.asdict(s) == before


def test_time_budget_ends_the_job():
    s = house()
    while not s.done:
        apply(s, "wait", {"ticks": 10})
    assert s.timed_out and s.tick == s.budget
    with pytest.raises(ActionError, match="over"):
        apply(s, "look", {"view": "counter"})


def test_repaired_joint_reads_dry_and_unrepaired_reads_wet():
    s = house({"type": "supply_leak", "id": "jin.kitchen.cold", "cause": "loose"})
    c = s.comps["jin.kitchen.cold"]
    assert sim.is_wet(s, c), "a running leak is wet from the first look"
    apply(s, "repair", {"tag": c.tag, "method": "tighten"})
    assert not sim.is_wet(s, c)
