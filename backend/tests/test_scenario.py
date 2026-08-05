import pytest

from app.video.scenario import ScenarioError, load_scenario

GOOD = """
name: fixture-demo
login: false
steps:
  - narration: "พิมพ์เป้าหมาย"
    action: type
    selector: "#goal"
    text: "ติว TGAT"
    sound: keystroke
  - narration: "รอระบบสร้างคอร์ส"
    action: wait_for
    selector: "#done"
    fit: speedup
"""


def test_load_valid_scenario(tmp_path):
    (tmp_path / "fixture-demo.yaml").write_text(GOOD, encoding="utf-8")
    s = load_scenario("fixture-demo", str(tmp_path))
    assert s.name == "fixture-demo"
    assert s.login is False
    assert len(s.steps) == 2
    assert s.steps[0].sound == "keystroke"
    assert s.steps[1].fit == "speedup"
    assert s.steps[0].fit == "speedup"       # default applied


def test_missing_file_raises(tmp_path):
    with pytest.raises(ScenarioError):
        load_scenario("nope", str(tmp_path))


def test_type_step_without_selector_raises(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        'name: bad\nsteps:\n  - narration: "x"\n    action: type\n    text: "hi"\n',
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError):
        load_scenario("bad", str(tmp_path))


def test_goto_step_without_url_raises(tmp_path):
    (tmp_path / "bad2.yaml").write_text(
        'name: bad2\nsteps:\n  - narration: "x"\n    action: goto\n', encoding="utf-8"
    )
    with pytest.raises(ScenarioError):
        load_scenario("bad2", str(tmp_path))


def test_empty_narration_raises(tmp_path):
    (tmp_path / "bad3.yaml").write_text(
        'name: bad3\nsteps:\n  - narration: ""\n    action: wait_ms\n    ms: 100\n',
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError):
        load_scenario("bad3", str(tmp_path))
