"""The website: built only from data in the repo, with every picture it links to, and numbers
that come from the runs."""
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from plumberbench import lander, results

ROOT = Path(__file__).resolve().parents[1]


def fake_run(tmp_path, swap=None):
    """A run log holding just the steps the front page uses, each with an 800x600 frame."""
    run = tmp_path / "run"
    run.mkdir()
    entries = []
    for step, cmd, _ in lander.FRAMES:
        tool, *values = cmd.split()
        if swap and step == swap:
            tool, values = "wait", ["1"]
        frame = f"step_{step:03d}.jpg"
        Image.new("RGB", (800, 600), (200, 200, 200)).save(run / frame)
        entries.append({"step": step, "tool": tool, "args": {f"a{i}": v for i, v in enumerate(values)}, "frame": frame})
    (run / "episode.jsonl").write_text("\n".join(json.dumps(e) for e in entries))
    return run


def fake_results(tmp_path):
    res = tmp_path / "results"
    (res / "models").mkdir(parents=True)
    policies = ["reference solver", "do nothing", "finish at once", "service all, never test"]
    scores = {p: {str(lv): ([0.95, 0.9] if p == "reference solver" else [0.4, 0.0] if "never" in p else [0.0, 0.0])
                  for lv in (1, 2, 3, 4)} for p in policies}
    (res / "ladder.json").write_text(json.dumps({"seeds": 2, "levels": [1, 2, 3, 4], "scores": scores}))
    rows = [{"level": 3, "seed": s, "mode": "pictures only", "score": sc, "repair": rep, "faults": f, "damage": 0,
             "time": "30/55", "free_actions": 3, "diagnosis_correct": rep == 1, "finished": True, "stop": "job over",
             "tool_calls": 20, "seconds": 50.0, "usage": {"input": 1000, "output": 100, "cache_read": 9000}}
            for s, sc, rep, f in ((0, 0.93, 1.0, "2/2"), (1, 0.4, 0.5, "1/2"))]
    (res / "models" / "m.json").write_text(json.dumps({"label": "Model M", "rows": rows}))
    return res


def test_command_reads_like_the_terminal():
    assert lander.command("run_tap", {"side": "both", "ticks": 1}) == "run_tap both 1"
    assert lander.command("inspect", {"tag": "C1"}) == "inspect C1"


def test_the_page_is_built_from_the_repo_data_with_every_picture(tmp_path):
    site = tmp_path / "site"
    page = lander.build(fake_run(tmp_path), site, fake_results(tmp_path))
    for src in set(re.findall(r'<img src="([^"]+)"', page)):
        assert (site / src).is_file(), src
    for _, cmd, _ in lander.FRAMES:
        assert f"<code>{cmd}</code>" in page
    for kind, _ in lander.FAULTS:
        assert f"<code>{kind}</code>" in page
    assert f'href="{lander.DEMO}"' in page and f'href="{lander.PLAY}"' in page
    assert 'id="results"' in page and "Model M" in page
    for _, _, _, url in lander.FACTS + [lander.IMO]:
        assert f'href="{url}"' in page  # every motivating number links to its source
    assert "1/2 clean" in page and "<td>1 of 2</td>" in page  # one clean job; one reported done with a fault left


def test_a_changed_run_fails_the_build(tmp_path):
    with pytest.raises(ValueError, match="update lander.FRAMES"):
        lander.build(fake_run(tmp_path, swap=lander.FRAMES[1][0]), tmp_path / "site", fake_results(tmp_path))


def test_play_has_a_page_while_the_online_server_is_off():
    """worker/index.js answers /play with this page until worker/online/ is deployed."""
    assert (ROOT / "site" / lander.OFFLINE).read_text() == lander.offline_page()
    assert lander.OFFLINE in (ROOT / "worker" / "index.js").read_text()
    assert lander.LOCAL_PLAY in (ROOT / "README.md").read_text()


def test_model_results_collect_runs_without_doubling(tmp_path):
    run = tmp_path / "codex-x-20261115-010101"
    run.mkdir()
    rows = [{"level": 1, "seed": 0, "mode": "facts", "score": 0.9, "repair": 1.0, "faults": "1/1", "damage": 0,
             "time": "20/45", "free_actions": 2, "diagnosis_correct": True, "finished": True, "stop": "job over",
             "tool_calls": 12, "seconds": 40.0, "usage": {"input": 100, "output": 10, "cache_read": 900}, "turns": 12}]
    (run / "summary.json").write_text(json.dumps(rows))
    out = tmp_path / "models"
    results.add(run, "Model X", out=out)
    path = results.add(run, "Model X", out=out)
    data = json.loads(path.read_text())
    assert path.name == "model-x.json" and len(data["rows"]) == 1 and "turns" not in data["rows"][0]
    st = results.stats(data["rows"])
    assert st["fixed_all"] == 1 and st["tokens_read"] == 1000 and st["cached_share"] == 0.9


def test_the_site_shows_the_committed_results():
    """The numbers on the committed page are the committed data's."""
    page = (ROOT / "site" / "main.html").read_text()
    _, models = lander.load_results(ROOT / "results")
    for m, rows in lander.pictures_jobs(models):
        assert m["label"] in page
        for lv in {r["level"] for r in rows}:
            at = [r for r in rows if r["level"] == lv]
            assert f"{sum(map(lander.is_clean, at))}/{len(at)} clean" in page


def test_the_chart_shows_pictures_only_jobs():
    a = {"label": "A", "rows": [{"level": 1, "seed": 0, "mode": "pictures only", "score": 1.0},
                                {"level": 1, "seed": 0, "mode": "facts", "score": 0.0}]}
    assert [len(rows) for _, rows in lander.pictures_jobs([a])] == [1]
