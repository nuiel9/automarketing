import os

import pytest

from app.video.demo import RenderStepError, render_demo
from app.video.scenario import Scenario, Step
from app.video.tts import Narration

FIXTURE_HTML = """<!doctype html><meta charset=utf-8>
<body style="background:#111;color:#fff;font-size:48px">
<input id=goal><button id=go onclick="setTimeout(()=>{document.body.insertAdjacentHTML('beforeend','<div id=done>เสร็จแล้ว</div>')},300)">go</button>
</body>"""


@pytest.fixture
def fixture_url(tmp_path):
    p = tmp_path / "fixture.html"
    p.write_text(FIXTURE_HTML, encoding="utf-8")
    return f"file://{p}"


def _fake_synth(tmp_path):
    import subprocess

    def _synth(text, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{abs(hash(text))}.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "sine=frequency=300:duration=1:sample_rate=24000", "-ac", "1", path],
            capture_output=True, check=True,
        )
        return Narration(text=text, path=path, seconds=1.0)

    return _synth


@pytest.mark.slow
def test_render_demo_returns_one_segment_per_step(tmp_path, fixture_url, monkeypatch):
    import app.video.demo as demo

    monkeypatch.setattr(demo, "synthesize", _fake_synth(tmp_path))
    scenario = Scenario(name="fx", login=False, steps=[
        Step(narration="พิมพ์", action="type", selector="#goal", text="hi", sound="keystroke"),
        Step(narration="กด", action="click", selector="#go", sound="click"),
        Step(narration="เสร็จ", action="wait_for", selector="#done"),
    ])
    segments = render_demo(scenario, str(tmp_path), base_url=fixture_url, login=None)

    assert len(segments) == 3
    for seg in segments:
        assert os.path.exists(seg.clip_path)
        assert seg.narration.seconds == 1.0
    assert segments[0].sound == "keystroke"


@pytest.mark.slow
def test_missing_selector_raises_with_screenshot(tmp_path, fixture_url, monkeypatch):
    import app.video.demo as demo

    monkeypatch.setattr(demo, "synthesize", _fake_synth(tmp_path))
    scenario = Scenario(name="fx", login=False, steps=[
        Step(narration="ไม่มีปุ่มนี้", action="click", selector="#missing", timeout_ms=1500),
    ])
    with pytest.raises(RenderStepError) as exc:
        render_demo(scenario, str(tmp_path), base_url=fixture_url, login=None)
    assert exc.value.step_index == 0
    assert os.path.exists(exc.value.screenshot_path)
