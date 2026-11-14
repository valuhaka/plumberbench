"""What the agent is told after each action.

`facts(state)` lists exactly what the current view shows, with the same
visibility rules the renderer uses: nothing hidden inside a pipe appears here
unless the part has been opened. The picture and the facts are two renderings
of one state.
"""
from __future__ import annotations

import json

from .sim import is_wet
from .world import BUCKET_CAP, FIXTURES, FLOW_NAME, State


def facts(s: State) -> list[dict]:
    out = []
    for c in s.in_view():
        f = {"tag": c.tag, "type": c.kind}
        if c.kind == "valve":
            f.update(role=c.role, line=c.line, handle=c.pos)
        elif c.kind == "joint":
            f.update(line=c.line, where=c.role, state="undone" if c.open else "closed",
                     wet=is_wet(s, c), puddle=c.puddle, stain=c.stain)
        elif c.kind == "trap":
            f.update(state="removed" if c.open else "installed", puddle=c.puddle)
            if c.open:
                f["inside"] = "blocked" if c.fault else "clear"
        elif c.kind == "cleanout":
            f.update(state="open" if c.open else "closed", puddle=c.puddle)
            if c.open:
                f["inside"] = "blocked" if c.fault else "clear"
        out.append(f)
    if s.room in FIXTURES and s.view == "counter":
        out.append({"type": "basin", "level": s.basin[s.room], "floor_water": s.overflow[s.room]})
        if s.flow_tick == s.tick and s.room in s.flow:
            out.append({"type": "tap", **{k: FLOW_NAME[v] for k, v in s.flow[s.room].items()}})
    if s.bucket_at and s.comps[s.bucket_at] in s.in_view():
        out.append({"type": "bucket", "under": s.comps[s.bucket_at].tag, "fill": s.bucket_fill})
    return out


def sounds(s: State) -> list[str]:
    heard = []
    spraying = [c for c in s.comps.values()
                if c.kind == "joint" and c.line != "drain" and c.open and s.tick == c.wet_tick]
    if spraying:
        here = any(c.room == s.room for c in spraying)
        heard.append("Water is spraying from an undone joint " + ("right here." if here else "somewhere in the house."))
    dripping = [c for c in s.comps.values()
                if c.room == s.room and c.kind == "joint" and not c.open and is_wet(s, c)]
    if dripping:
        heard.append("Dripping in this room.")
    return heard


def status(s: State) -> str:
    bucket = "bucket unused"
    if s.bucket_at:
        bucket = f"bucket under {s.comps[s.bucket_at].tag} ({s.bucket_fill}/{BUCKET_CAP})"
    return (f"step {s.step} | time {s.tick}/{s.budget} | damage {s.damage} | "
            f"{s.room}/{s.view} | {bucket} | washers {s.washers}")


def text(s: State, message: str, with_facts: bool) -> str:
    """One response, in labelled sections:

        STATUS:   step, time used/budget, damage, where you are, bucket, washers
        RESULT:   what the action did
        YOU HEAR: sounds, or "nothing unusual"
        IN VIEW:  tags of the parts in the current view
        FACTS:    (facts mode only) JSON list of what the view shows
    """
    lines = ["STATUS: " + status(s), "RESULT: " + message]
    if s.done:
        lines.append("RESULT: The job is over. No further actions are possible.")
        return "\n".join(lines)
    lines.append("YOU HEAR: " + (" ".join(sounds(s)) or "nothing unusual."))
    lines.append("IN VIEW: " + " ".join(c.tag for c in s.in_view()))
    if with_facts:
        lines.append("FACTS: " + json.dumps(facts(s), separators=(",", ":")))
    return "\n".join(lines)


def error(s: State, message: str) -> str:
    return f"STATUS: {status(s)}\nERROR: {message} No time passed."
