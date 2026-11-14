"""One episode: state + rules + observations + log.

Used the same way by the MCP server, the tests, the human-play loop and the
in-process reference solver.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import observe, sim
from .generate import generate
from .judge import score


@dataclass
class Obs:
    """One response. Every front-end (MCP, terminal, browser) shows exactly `text` and `image`."""

    text: str
    image: bytes | None = None          # JPEG of the view, or of a close-up after `inspect`
    hotspots: list = field(default_factory=list)  # boxes of the tag labels drawn on `image`
    facts: list = field(default_factory=list)
    error: bool = False


class Episode:
    def __init__(self, seed: int, level: int, facts: bool = True, render: bool = True,
                 log_dir: str | Path | None = None):
        self.state = generate(seed, level)
        self.with_facts = facts
        self.render = render
        self.actions: list[tuple[str, dict]] = []
        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            (self.log_dir / "episode.jsonl").write_text("")
            self._write_result()

    def act(self, tool: str, **args) -> Obs:
        s = self.state
        try:
            message = sim.apply(s, tool, args)
        except sim.ActionError as e:
            return Obs(text=observe.error(s, str(e)), error=True)
        self.actions.append((tool, args))
        obs = Obs(text=observe.text(s, message, self.with_facts), facts=observe.facts(s))
        if self.render:
            from .render import render  # imported late so headless tests need no GL
            focus = s.by_tag(args["tag"]).tag if tool == "inspect" else None
            obs.image, obs.hotspots = render(s, focus)
        self._log(tool, args, obs)
        return obs

    def result(self) -> dict:
        r = score(self.state)
        r.update(seed=self.state.seed, level=self.state.level, steps=self.state.step)
        return r

    # ------------------------------------------------------------- logging

    def _log(self, tool: str, args: dict, obs: Obs) -> None:
        if not self.log_dir:
            return
        s = self.state
        frame = None
        if obs.image:
            frame = f"step_{s.step:03d}.jpg"
            (self.log_dir / frame).write_bytes(obs.image)
        row = {"step": s.step, "tool": tool, "args": args, "tick": s.tick,
               "damage": s.damage, "text": obs.text, "frame": frame}
        with (self.log_dir / "episode.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        self._write_result()

    def _write_result(self) -> None:
        r = self.result()
        r["faults"] = self.state.faults  # ground truth, for the log only
        (self.log_dir / "result.json").write_text(json.dumps(r, indent=2))
