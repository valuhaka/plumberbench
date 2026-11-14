"""The reward: what must score high, what must score nothing, and that it is stable."""
import random

import pytest

from plumberbench import baselines
from plumberbench.env import Episode
from plumberbench.generate import LEVELS, generate
from plumberbench.judge import replay, score
from plumberbench.solver import Solver

SEEDS = range(40)
CASES = [(seed, level) for level in LEVELS for seed in SEEDS]


def play(policy, seed, level):
    ep = Episode(seed, level, render=False)
    policy(lambda tool, args: ep.act(tool, **args).text)
    return ep


def reference(call):
    Solver(call).run()


@pytest.mark.parametrize("level", LEVELS)
def test_reference_solver_repairs_every_house(level):
    results = [play(reference, seed, level).result() for seed in SEEDS]
    assert all(r["repair"] == 1.0 for r in results)
    assert all(all(r["functional_test"].values()) for r in results)
    assert all(r["diagnosis_correct"] for r in results)
    assert min(r["score"] for r in results) > 0.85
    assert sum(r["score"] for r in results) / len(results) > 0.9


@pytest.mark.parametrize("name", ["do nothing", "finish at once", "name every diagnosis",
                                  "close the main valve", "repair everything"])
def test_exploits_score_zero(name):
    for seed, level in CASES:
        assert play(baselines.POLICIES[name], seed, level).result()["score"] == 0.0, (name, seed, level)


@pytest.mark.parametrize("level", LEVELS)
def test_blind_servicing_is_well_below_the_reference(level):
    blind = [play(baselines.service_without_testing, s, level).result()["score"] for s in SEEDS]
    ref = [play(reference, s, level).result()["score"] for s in SEEDS]
    assert sum(blind) / len(blind) < sum(ref) / len(ref) - 0.3


def test_fixing_one_of_two_faults_earns_about_half():
    s = generate(0, 3, faults=[{"type": "aerator_clog", "id": "aer.kitchen"},
                               {"type": "aerator_clog", "id": "aer.bathroom"}])
    s.comps["aer.kitchen"].fault = None
    s.done, s.diagnosis = True, ["aerator_clog"]
    r = score(s)
    assert r["repair"] == 0.5 and 0.45 < r["score"] <= 0.5


def test_leaving_the_house_worse_costs_a_quarter_each():
    s = generate(0, 1, faults=[{"type": "aerator_clog", "id": "aer.kitchen"}])
    s.comps["aer.kitchen"].fault = None
    assert score(s)["repair"] == 1.0
    s.comps["stop.kitchen.hot"].pos = "closed"
    s.comps["trap.bathroom"].open = True
    r = score(s)
    assert r["repair"] == 0.5 and len(r["left_worse"]) == 2


def test_replaying_the_actions_gives_the_same_score():
    for seed, level in [(3, 1), (5, 2), (8, 3), (13, 4)]:
        ep = play(reference, seed, level)
        again = replay(seed, level, ep.actions)
        assert score(again) == score(ep.state)


def test_score_formula_and_functional_test_always_agree():
    """Full marks for repair if and only if every tap, drain and joint passes."""
    rng = random.Random(0)
    full = 0
    for i in range(400):
        level = 1 + i % 4
        ep = Episode(i, level, render=False)
        call = lambda tool, args: ep.act(tool, **args).text
        if i % 2:
            Solver(call).run()                       # a good end state...
            ep.state.done = False
            baselines.random_walk(call, rng, 6)      # ...then disturbed at random
        else:
            baselines.random_walk(call, rng, 60)
        r = ep.result()
        assert r["consistent"], (i, level, r)
        full += r["repair"] == 1.0
    assert 20 < full < 380, "the check should see both passing and failing houses"


def test_observations_never_carry_ground_truth():
    """Facts carry no fault field, and a pipe's inside shows only once it is opened.

    The tenant's complaint may use words like "clogged": it is hearsay, and at
    level 2 and above it is often wrong.
    """
    for seed, level in CASES[::7]:
        ep = Episode(seed, level, render=False)
        for view in ("counter", "under_sink"):
            obs = ep.act("look", view=view)
            body = obs.text.split("\n", 1)[1]
            assert obs.text.startswith("STATUS: ") and "\nRESULT: " in obs.text and "\nIN VIEW: " in obs.text
            assert "fault" not in body and "sludge" not in body and "crusted" not in body
            for f in obs.facts:
                assert "fault" not in f
                assert "inside" not in f or f["state"] in ("removed", "open")
            for c in ep.state.comps.values():
                if "." in c.id:  # internal names such as jin.kitchen.cold
                    assert c.id not in obs.text, "internal part names must not reach the agent"


def test_one_episode_per_server_cannot_be_reset_by_finishing_twice():
    ep = Episode(1, 1, render=False)
    ep.act("finish", diagnosis=[])
    assert ep.act("briefing").error and ep.act("finish", diagnosis=["trap_clog"]).error
    assert ep.result()["score"] == 0.0
