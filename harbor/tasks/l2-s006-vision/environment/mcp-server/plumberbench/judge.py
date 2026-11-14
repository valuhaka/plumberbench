"""The judge. Plain code over simulator state; no model is involved.

Score, in [0, 1]:

    repair = faults fixed / faults present  -  0.25 per thing left worse
    score  = repair * (0.70 + 0.15 * dry + 0.10 * quick + 0.05 * named)

    dry    = 1 - damage / DAMAGE_CAP          (floored at 0)
    quick  = 1 - time used / time budget
    named  = 1 if the reported diagnosis is exactly the set of fault types
             (both lists are in the result, so a wrong one shows why)

Everything is multiplied by `repair`, so a run that fixes nothing scores 0
whatever else it does. "Left worse" means a joint left undone, a trap or plug
left out, a valve left less open than it started, or a sound joint whose
washer was crushed by tightening it when it was not loose.

`functional_test` is an independent check of the same thing: it runs every tap
and watches every drain on a copy of the house. A full repair must pass it and
anything less must fail it; the test suite asserts that the two always agree.
"""
from __future__ import annotations

import copy

from .generate import generate
from .sim import ActionError, _tick, apply
from .world import DAMAGE_CAP, FIXTURES, PRESSURE, SIDES, State

W_REPAIR, W_DRY, W_QUICK, W_NAMED = 0.70, 0.15, 0.10, 0.05
REGRESSION_PENALTY = 0.25


def resolved(s: State) -> list[bool]:
    out = []
    for f in s.faults:
        c = s.comps[f["id"]]
        out.append(c.pos == "open" if f["type"] == "valve_not_open" else c.fault is None)
    return out


def regressions(s: State) -> list[str]:
    faulty_valves = {f["id"] for f in s.faults if f["type"] == "valve_not_open"}
    original = {f["id"] for f in s.faults}
    found = []
    for c in s.comps.values():
        if c.fault and c.id not in original:
            found.append(f"{c.tag} damaged")
        if c.kind in ("joint", "trap", "cleanout") and c.open:
            found.append(f"{c.tag} left open")
        if c.kind == "valve" and c.id not in faulty_valves:
            if PRESSURE[c.pos] < PRESSURE[s.initial_pos[c.id]]:
                found.append(f"{c.tag} left {c.pos}")
    return found


def functional_test(s: State) -> dict[str, bool]:
    """Run every tap, watch every drain, look for drips. Works on a copy."""
    t = copy.deepcopy(s)
    t.budget = 10**9
    start = t.emitted
    checks = {}
    for fx in FIXTURES:
        for side in SIDES:
            full = True
            for _ in range(3):
                _tick(t, {fx: (side,)})
                full = full and t.flow[fx][side] == 2
            checks[f"{fx} {side} flow"] = full
        for _ in range(6):
            _tick(t, None)
        checks[f"{fx} drains"] = t.basin[fx] == 0
    checks["nothing drips"] = t.emitted == start
    checks["everything refitted"] = not any(
        c.open for c in t.comps.values() if c.kind in ("joint", "trap", "cleanout"))
    return checks


def score(s: State) -> dict:
    fixed = resolved(s)
    worse = regressions(s)
    repair = max(0.0, sum(fixed) / len(fixed) - REGRESSION_PENALTY * len(worse))
    dry = max(0.0, 1 - s.damage / DAMAGE_CAP)
    quick = max(0.0, 1 - s.tick / s.budget)
    reported = sorted(set(s.diagnosis or []))
    present = sorted({f["type"] for f in s.faults})
    named = float(reported == present)
    total = repair * (W_REPAIR + W_DRY * dry + W_QUICK * quick + W_NAMED * named)
    checks = functional_test(s)
    return {
        "score": round(total, 4),
        "repair": round(repair, 4),
        "faults_fixed": sum(fixed),
        "faults_total": len(fixed),
        "left_worse": worse,
        "damage": s.damage,
        "time_used": s.tick,
        "time_budget": s.budget,
        "diagnosis_correct": bool(named),
        "diagnosis_reported": reported,   # what `finish` named
        "diagnosis_expected": present,    # the fault types actually present; must match exactly
        "finished": s.done and not s.timed_out,
        "timed_out": s.timed_out,
        "functional_test": checks,
        "consistent": all(checks.values()) == (all(fixed) and not worse),
    }


def replay(seed: int, level: int, actions: list[tuple[str, dict]]) -> State:
    """Rebuild the final state from the seed and the list of actions taken."""
    s = generate(seed, level)
    for tool, args in actions:
        try:
            apply(s, tool, dict(args))
        except ActionError:
            pass
    return s
