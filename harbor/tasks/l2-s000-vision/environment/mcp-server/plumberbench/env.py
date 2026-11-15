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


def _with_line(text: str, line: str) -> str:
    """Add a section line before FACTS (which, when present, stays last)."""
    lines = text.split("\n")
    at = next((i for i, l in enumerate(lines) if l.startswith("FACTS: ")), len(lines))
    return "\n".join(lines[:at] + [line] + lines[at:])


class Episode:
    def __init__(self, seed: int, level: int, facts: bool = True, render: bool = True,
                 log_dir: str | Path | None = None):
        self.state = generate(seed, level)
        self._shown: tuple[str, int] | None = None  # (digest, step) of the last picture sent
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
        self.actions.append((tool, args))  # refused ones too: they count toward the free-action limit
        try:
            message = sim.apply(s, tool, args)
        except sim.ActionError as e:
            obs = Obs(text=observe.error(s, str(e)), error=True)
            self._log(tool, args, obs, refused=True)
            return obs
        if tool == "inspect" and s.level >= 5 and not self.with_facts:
            message = observe.close_look(s, args["tag"], message)
        obs = Obs(text=observe.text(s, message, self.with_facts), facts=observe.facts(s))
        if self.render:
            from .render import render  # imported late so headless tests need no GL
            focus = s.by_tag(args["tag"]).tag if tool == "inspect" else None
            image, hotspots, content = render(s, focus)
            if self._shown and self._shown[0] == content:
                # Nothing in view changed: no new picture, and the text says which one still holds.
                obs.text = _with_line(obs.text, f"PICTURE: unchanged since step {self._shown[1]}.")
            else:
                obs.image, obs.hotspots = image, hotspots
                self._shown = (content, s.step)
        self._log(tool, args, obs)
        return obs

    def picture_step(self) -> int | None:
        """Step of the picture currently on screen, if any."""
        return self._shown[1] if self._shown else None

    def result(self) -> dict:
        r = score(self.state)
        r.update(seed=self.state.seed, level=self.state.level, steps=self.state.step)
        return r

    def report(self) -> dict:
        """The full result, with what the faults actually were. For logs and for after the job."""
        r = self.result()
        r["faults"] = [{**f, "tag": self.state.comps[f["id"]].tag} for f in self.state.faults]
        return r

    # ------------------------------------------------------------- logging

    def _log(self, tool: str, args: dict, obs: Obs, refused: bool = False) -> None:
        if not self.log_dir:
            return
        s = self.state
        frame = None
        if obs.image:
            frame = f"step_{s.step:03d}.jpg"
            (self.log_dir / frame).write_bytes(obs.image)
        row = {"step": s.step, "tool": tool, "args": args, "tick": s.tick,
               "damage": s.damage, "text": obs.text, "frame": frame, "refused": refused}
        with (self.log_dir / "episode.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        self._write_result()

    def _write_result(self) -> None:
        (self.log_dir / "result.json").write_text(json.dumps(self.report(), indent=2))
