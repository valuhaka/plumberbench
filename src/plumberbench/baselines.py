"""Scripted policies the judge must not reward.

Each takes `call(tool, args) -> text`, like the reference solver. They exist
to test the reward, and they are the first things an exploit hunter will try.
"""
from __future__ import annotations

import random

from .solver import Seen

DIAGNOSES = ["trap_clog", "branch_clog", "supply_leak", "drain_leak", "aerator_clog", "valve_not_open"]


def washers(seen: Seen) -> int:
    return int(seen.text.split("washers ")[1].split()[0])


def do_nothing(call) -> None:
    """Never touch the environment."""


def finish_now(call) -> None:
    """Stop at once, naming a diagnosis without repairing anything."""
    call("finish", {"diagnosis": ["trap_clog"]})


def name_everything(call) -> None:
    """Stop at once and claim every diagnosis on the list."""
    call("finish", {"diagnosis": DIAGNOSES})


def close_main(call) -> None:
    """Shut the water off for the whole house: every leak stops, nothing works."""
    seen = Seen(call("go", {"room": "utility"}), None)
    main = seen.one("valve", role="main")
    call("set_valve", {"tag": main["tag"], "position": "closed"})
    call("finish", {"diagnosis": ["supply_leak"]})


def repair_everything(call) -> None:
    """No diagnosis: open, tighten and clear every part in sight until time runs out."""

    def step(tool, **args) -> Seen:
        return Seen(call(tool, args), None)

    for room in ("kitchen", "bathroom", "utility"):
        seen = step("go", room=room) if room != "kitchen" else step("look", view="counter")
        for a in seen.all("aerator"):
            step("repair", tag=a["tag"], method="clear")
        if room != "utility":
            seen = step("look", view="under_sink")
        for v in seen.all("valve"):
            if v["role"] != "spare" and v["handle"] != "open":
                step("set_valve", tag=v["tag"], position="open")
        for j in seen.all("joint"):
            step("repair", tag=j["tag"], method="tighten")
        for part in seen.all("trap") + seen.all("cleanout"):
            step("place_bucket", tag=part["tag"])
            step("open_joint", tag=part["tag"])
            step("repair", tag=part["tag"], method="clear")
            step("close_joint", tag=part["tag"])
    call("finish", {"diagnosis": DIAGNOSES})


def service_without_testing(call) -> None:
    """Careful but blind: inspect and service every part, never run a tap."""

    def step(tool, **args) -> Seen:
        return Seen(call(tool, args), None)

    found = set()
    for room in ("kitchen", "bathroom", "utility"):
        seen = step("go", room=room) if room != "kitchen" else step("look", view="counter")
        for a in seen.all("aerator"):
            if "crusted" in step("inspect", tag=a["tag"]).text:
                step("repair", tag=a["tag"], method="clear")
                found.add("aerator_clog")
        if room != "utility":
            seen = step("look", view="under_sink")
        for v in seen.all("valve"):
            if v["role"] != "spare" and v["handle"] != "open":
                step("set_valve", tag=v["tag"], position="open")
                found.add("valve_not_open")
        for j in seen.all("joint"):
            if "loose" in step("inspect", tag=j["tag"]).text:
                step("repair", tag=j["tag"], method="tighten")
                found.add("supply_leak" if j["line"] != "drain" else "drain_leak")
        for part in seen.all("trap") + seen.all("cleanout"):
            if washers(seen) == 0:
                break
            step("place_bucket", tag=part["tag"])
            if "sludge" in step("open_joint", tag=part["tag"]).text:
                step("repair", tag=part["tag"], method="clear")
                found.add("trap_clog" if part["type"] == "trap" else "branch_clog")
            seen = step("close_joint", tag=part["tag"])
    call("finish", {"diagnosis": sorted(found)})


def random_walk(call, rng: random.Random, steps: int = 40) -> None:
    """Random legal-looking actions. Used to test the judge, not as a baseline."""
    seen = Seen(call("briefing", {}), None)
    for _ in range(steps):
        tags = [f["tag"] for f in seen.facts if "tag" in f]
        choices = [
            ("go", {"room": rng.choice(["kitchen", "bathroom", "utility"])}),
            ("look", {"view": rng.choice(["counter", "under_sink", "wall"])}),
            ("run_tap", {"side": rng.choice(["cold", "hot", "both"]), "ticks": rng.randint(1, 3)}),
            ("wait", {"ticks": rng.randint(1, 3)}),
        ]
        if tags:
            tag = rng.choice(tags)
            choices += [
                ("inspect", {"tag": tag}),
                ("set_valve", {"tag": tag, "position": rng.choice(["open", "half", "closed"])}),
                ("place_bucket", {"tag": tag}),
                ("open_joint", {"tag": tag}),
                ("close_joint", {"tag": tag}),
                ("repair", {"tag": tag, "method": rng.choice(["tighten", "clear"])}),
            ] * 2
        tool, args = rng.choice(choices)
        new = Seen(call(tool, args), None)
        if new.over:
            return
        if not new.error:
            seen = new


POLICIES = {
    "do nothing": do_nothing,
    "finish at once": finish_now,
    "name every diagnosis": name_everything,
    "close the main valve": close_main,
    "repair everything": repair_everything,
    "service all, never test": service_without_testing,
}
