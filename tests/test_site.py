"""The front page: its frames are the commands it claims, and its links go somewhere real."""
import json
from pathlib import Path

import pytest
from PIL import Image

from plumberbench import lander


def fake_run(tmp_path, swap=None):
    """A run log holding just the steps the front page uses, each with an 800x600 frame."""
    entries = []
    for step, cmd, _ in lander.FRAMES:
        tool, *values = cmd.split()
        if swap and step == swap:
            tool, values = "wait", ["1"]
        frame = f"step_{step:03d}.jpg"
        Image.new("RGB", (800, 600), (200, 200, 200)).save(tmp_path / frame)
        entries.append({"step": step, "tool": tool, "args": {f"a{i}": v for i, v in enumerate(values)},
                        "frame": frame})
    (tmp_path / "episode.jsonl").write_text("\n".join(json.dumps(e) for e in entries))
    return tmp_path


def test_command_reads_like_the_terminal():
    assert lander.command("run_tap", {"side": "both", "ticks": 1}) == "run_tap both 1"
    assert lander.command("inspect", {"tag": "C1"}) == "inspect C1"


def test_the_page_shows_each_frame_with_its_command(tmp_path):
    page = lander.build(fake_run(tmp_path))
    assert page.count('<img src="data:image/jpeg;base64,') == len(lander.FRAMES)
    for _, cmd, caption in lander.FRAMES:
        assert f"<code>{cmd}</code>" in page
    assert f'href="{lander.DEMO}"' in page and f'href="{lander.REPO}#playing-it-yourself"' in page


def test_a_changed_run_fails_the_build(tmp_path):
    with pytest.raises(ValueError, match="update lander.FRAMES"):
        lander.build(fake_run(tmp_path, swap=lander.FRAMES[1][0]))


def test_try_the_house_points_at_a_readme_section():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "\n## Playing it yourself\n" in readme
