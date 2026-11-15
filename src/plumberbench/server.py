"""MCP server: one PlumberBench episode, served over streamable HTTP.

    PB_SEED=7 PB_LEVEL=3 python -m plumberbench.server

Settings (environment variables):
    PB_SEED, PB_LEVEL     which house (default 0, 1)
    PB_FACTS              1: every response also lists what the view shows as
                          FACTS (default); 0: images and sounds only
    PB_RENDER             1: attach a JPEG of the view to every response (default)
    PB_LOG_DIR            where the action log, frames and result.json go
                          (default /var/plumberbench); keep it out of the
                          agent's container
    PB_PORT               default 8000

Each tool call is one action. Actions run one at a time; a call that arrives
while another is running is refused with no effect.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pydantic import Field
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from . import observe
from .env import Episode
from .world import DIAGNOSES, DIAGNOSIS_TEXT

SEED = int(os.environ.get("PB_SEED", "0"))
LEVEL = int(os.environ.get("PB_LEVEL", "1"))
FACTS = os.environ.get("PB_FACTS", "1") == "1"
RENDER = os.environ.get("PB_RENDER", "1") == "1"
LOG_DIR = os.environ.get("PB_LOG_DIR", "/var/plumberbench")

episode = Episode(SEED, LEVEL, facts=FACTS, render=RENDER, log_dir=LOG_DIR)
lock = threading.Lock()

mcp = FastMCP(
    "plumberbench",
    instructions=(
        "You are a plumber in a small house with a kitchen, a bathroom and a utility room. "
        "Every tool call is one action. Most actions take time, shown in the status line as "
        "time used/time budget. Each response has a picture of the view you are looking at, with "
        "every part tagged (V valve, J joint, T trap, C cleanout plug, A tap aerator), and text in "
        "sections: STATUS, RESULT, YOU HEAR, IN VIEW. You can only act on parts in the current view. "
        "At most 200 actions may take no time (refused ones included); then the job ends. "
        "Call `briefing` first. Call `finish` once, when the job is done."
    ),
)

Tag = Annotated[str, Field(description="A part's tag as shown in the view, e.g. V3 or J12.")]


def _respond(tool: str, **args):
    if not lock.acquire(blocking=False):
        return observe.error(episode.state, "Another action is still in progress. Actions run one at a time.")
    try:
        obs = episode.act(tool, **args)
    finally:
        lock.release()
    if obs.image is None:
        return obs.text
    return [obs.text, Image(data=obs.image, format="jpeg")]


@mcp.tool
def briefing():
    """Hear the tenant's complaint again and see where you are standing. Takes no time."""
    return _respond("briefing")


@mcp.tool
def go(room: Literal["kitchen", "bathroom", "utility"]):
    """Walk to another room. Takes 2 time units.

    You arrive facing the counter (kitchen, bathroom) or the wall of pipes (utility).
    """
    return _respond("go", room=room)


@mcp.tool
def look(view: Literal["counter", "under_sink", "wall"]):
    """Look at a different part of the room you are in. Takes no time.

    kitchen and bathroom: counter (basin, tap, aerator) or under_sink (supply
    lines, stop valves, joints, trap). utility: wall (main valve, heater valve,
    branch valves, drain cleanout).
    """
    return _respond("look", view=view)


@mcp.tool
def inspect(tag: Tag):
    """Examine one part in the current view closely. Takes 3 time units.

    The picture returned is a close-up of the part. Valves: how far open. Joints: whether the nut is loose and whether it is
    seeping. Aerators: whether the screen is blocked. Traps cannot be seen into
    unless removed. Tapping the cleanout tells whether the pipe behind it holds water.
    """
    return _respond("inspect", tag=tag)


@mcp.tool
def run_tap(side: Literal["cold", "hot", "both"],
            ticks: Annotated[int, Field(ge=1, le=5, description="How long to run it, 1-5.")]):
    """Run the tap in this room (kitchen or bathroom) for some ticks, then turn it off.

    Takes as many time units as ticks. Water goes into the basin and down the
    drain if the drain is clear. The response shows the flow on the last tick.
    """
    return _respond("run_tap", side=side, ticks=ticks)


@mcp.tool
def wait(ticks: Annotated[int, Field(ge=1, le=10, description="How long to wait, 1-10.")]):
    """Do nothing for some ticks and watch. Takes as many time units as ticks."""
    return _respond("wait", ticks=ticks)


@mcp.tool
def set_valve(tag: Tag, position: Literal["open", "half", "closed"]):
    """Turn a valve in the current view to a position. Takes 1 time unit.

    A closed valve takes the pressure off everything downstream of it. Leave
    every valve at least as open as you found it, unless it was meant to be open.
    """
    return _respond("set_valve", tag=tag, position=position)


@mcp.tool
def place_bucket(tag: Tag):
    """Empty the bucket and set it under a joint, trap or cleanout in the current view. Takes 1 time unit.

    The bucket catches drips and anything that pours out when the part is
    opened, up to 10 units. Water that misses it ends up on the floor as damage.
    """
    return _respond("place_bucket", tag=tag)


@mcp.tool
def open_joint(tag: Tag):
    """Undo a joint, remove a trap, or take out the cleanout plug. Takes 3 time units.

    Whatever is inside comes out. A supply joint undone while its line is under
    pressure sprays water. A removed trap or open plug shows what is inside.
    """
    return _respond("open_joint", tag=tag)


@mcp.tool
def close_joint(tag: Tag):
    """Refit a part you opened, with a new washer. Takes 3 time units and uses one washer.

    A joint refitted on a new washer no longer leaks. You carry a limited
    number of washers (shown in the status line).
    """
    return _respond("close_joint", tag=tag)


@mcp.tool
def repair(tag: Tag, method: Literal["tighten", "clear"]):
    """Fix a part in the current view. Takes 3 time units.

    tighten: a joint's nut. Fixes a loose nut; forcing a nut that is already
    tight crushes its washer and makes it leak. clear: an aerator screen, or a
    trap or cleanout that has been opened first.
    """
    return _respond("repair", tag=tag, method=method)


@mcp.tool
def finish(diagnosis: Annotated[list[Literal[DIAGNOSES]], Field(  # type: ignore[valid-type]
        description="Every fault type you found and fixed. " + " ".join(
            f"{d}: {DIAGNOSIS_TEXT[d]}." for d in DIAGNOSES))]):
    """Report the job done and stop. Takes no time. After this, no action is possible.

    The house is then tested: every tap must run full on hot and cold, every
    basin must drain, nothing may drip, every part must be refitted and no
    valve left more closed than you found it.
    """
    return _respond("finish", diagnosis=diagnosis)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request):
    return PlainTextResponse("ok")


def main() -> None:
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PB_PORT", "8000")),
            path="/mcp")


if __name__ == "__main__":
    main()
