"""What the agent is told after each action.

`facts(state)` lists exactly what the current view shows, with the same
visibility rules the renderer uses: nothing hidden inside a pipe appears here
unless the part has been opened. The picture and the facts are two renderings
of one state.
"""
from __future__ import annotations

import json

from .sim import is_wet
from .world import BUCKET_CAP, FIXTURES, FLOW_NAME, FREE_ACTION_LIMIT, State


def facts(s: State) -> list[dict]:
    out = []
    for c in s.in_view():
        f = {"tag": c.tag, "type": c.kind}
        if c.kind == "valve":
            f.update(role=c.role, line=c.line, handle=c.pos)
        elif c.kind == "joint":
            f.update(line=c.line, where=c.role, state="undone" if c.open else "closed",
                     wet=is_wet(s, c), puddle=c.puddle, stain=c.stain)
            if s.level >= 5 and s.inspected == c.id and not c.open:  # what the close-up draws
                f["nut"] = "backed off" if c.fault == "loose" else "home"
        elif c.kind == "trap":
            f.update(state="removed" if c.open else "installed", puddle=c.puddle)
            if c.open:
                f["inside"] = {"partial": "partly blocked", None: "clear"}.get(c.fault, "blocked")
        elif c.kind == "cleanout":
            f.update(state="open" if c.open else "closed", puddle=c.puddle)
            if c.open:
                f["inside"] = "blocked" if c.fault else "clear"
        elif c.kind == "aerator" and s.level >= 5 and s.inspected == c.id:  # what the close-up draws
            f["scale"] = bool(c.fault)
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
    if dripping and s.level < 5:  # at level 5 only the picture shows a drip
        heard.append("Dripping in this room.")
    return heard


def close_look(s: State, tag, message: str) -> str:
    """Level 5, pictures only: what `inspect` finds on a joint, valve or aerator is in the
    close-up picture (a backed-off nut, the lever, white scale), not in words. Sounds and
    the inside of an opened part are still told."""
    c = s.by_tag(tag)
    if c is not None and c.kind in ("joint", "valve", "aerator") and not c.open:
        return f"You looked closely at {c.tag}. The close-up shows what you found."
    return message


def status(s: State) -> str:
    bucket = "bucket unused"
    if s.bucket_at:
        bucket = f"bucket under {s.comps[s.bucket_at].tag} ({s.bucket_fill}/{BUCKET_CAP})"
    return (f"step {s.step} | time {s.tick}/{s.budget} | damage {s.damage} | "
            f"{s.room}/{s.view} | {bucket} | washers {s.washers} | "
            f"free actions {s.free_actions}/{FREE_ACTION_LIMIT}")


def text(s: State, message: str, with_facts: bool) -> str:
    """One response, in labelled sections:

        STATUS:   step, time used/budget, damage, where you are, bucket, washers,
                  actions so far that took no time / the limit
        RESULT:   what the action did
        YOU HEAR: sounds, or "nothing unusual"
        IN VIEW:  tags of the parts in the current view
        PICTURE:  only when no new picture is sent: nothing in view changed since that step
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
