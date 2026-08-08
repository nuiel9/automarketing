import os

import pytest

from app.video.demo import RenderStepError, render_demo
from app.video.scenario import Scenario, Step
from app.video.tts import Narration

FIXTURE_HTML = """<!doctype html><meta charset=utf-8>
<body style="background:#111;color:#fff;font-size:48px">
<input id=goal><button id=go onclick="setTimeout(()=>{document.body.insertAdjacentHTML('beforeend','<div id=done>เสร็จแล้ว</div>')},300)">go</button>
</body>"""

# A busy-wait blocks the page's `load` event for ~900ms, making page.goto()
# itself slow -- the way a real production page (or a login step doing real
# network work) is slow -- without needing a network. This reproduces the
# timeline-origin bug: if t0 is captured after goto/login instead of right
# after context.new_page(), that ~900ms of real wall-clock time spent inside
# goto is silently dropped from the mark timeline, and every cut clip starts
# too early relative to the actual recording.
SLOW_LOAD_FIXTURE_HTML = """<!doctype html><meta charset=utf-8>
<script>
  var start = Date.now();
  while (Date.now() - start < 900) {}
</script>
<body style="background:#111;color:#fff;font-size:48px">
<input id=goal><button id=go onclick="setTimeout(()=>{document.body.insertAdjacentHTML('beforeend','<div id=done>เสร็จแล้ว</div>')},300)">go</button>
</body>"""


@pytest.fixture
def fixture_url(tmp_path):
    p = tmp_path / "fixture.html"
    p.write_text(FIXTURE_HTML, encoding="utf-8")
    return f"file://{p}"


@pytest.fixture
def slow_load_fixture_url(tmp_path):
    p = tmp_path / "slow_fixture.html"
    p.write_text(SLOW_LOAD_FIXTURE_HTML, encoding="utf-8")
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


@pytest.mark.slow
def test_marks_share_timeline_origin_with_recording(tmp_path, slow_load_fixture_url, monkeypatch):
    """t0 must be captured immediately after context.new_page() -- when
    Playwright's session recording actually starts -- not after the
    subsequent goto()/login. Capturing it late silently drops the real
    wall-clock time spent in goto/login from the mark timeline, so every
    step's clip gets cut starting too early and shows the wrong footage.

    A fast local file:// goto hides this (the pre-loop gap rounds to noise),
    so this test uses slow_load_fixture_url, whose page blocks its own
    `load` event for ~900ms, to put a real, measurable gap between
    page-creation time and step-loop time. We assert on the first cut
    command's raw "-ss" value (marks[0][0], read straight off Python's
    monotonic clock) rather than comparing against the session recording's
    probed duration: an earlier version of this test compared against
    ffprobe's measured video duration and that duration turned out to be
    noisy on its own (observed ranging ~1.7-2.8s across otherwise-identical
    runs, apparently because Playwright's recorded video doesn't grow
    proportionally with a render-blocked delay but does track live/async
    waits, and has roughly a 1s floor) -- noisy enough to false-fail a
    correct render. marks[0][0] carries no such noise: with the bug, step 0
    always starts at ~0.00s (t0 was just captured, right before the loop);
    fixed, it starts at ~0.9s (t0 was captured before the ~900ms load, so
    that time is correctly folded into the first step's start).
    """
    import app.video.demo as demo

    monkeypatch.setattr(demo, "synthesize", _fake_synth(tmp_path))

    cut_commands = []
    original_run = demo.run

    def _capture_run(cmd):
        cut_commands.append(cmd)
        return original_run(cmd)

    monkeypatch.setattr(demo, "run", _capture_run)

    scenario = Scenario(name="fx", login=False, steps=[
        Step(narration="พิมพ์", action="type", selector="#goal", text="hi"),
        Step(narration="กด", action="click", selector="#go"),
        Step(narration="เสร็จ", action="wait_for", selector="#done"),
    ])
    render_demo(scenario, str(tmp_path), base_url=slow_load_fixture_url, login=None)

    first_cut = cut_commands[0]
    first_mark_start = float(first_cut[first_cut.index("-ss") + 1])

    assert first_mark_start > 0.5, (
        f"step 0 was cut starting at {first_mark_start:.3f}s, but the fixture "
        "page blocks its own load for ~900ms before step 0 can even run -- "
        "the mark timeline is missing that time, meaning t0 was captured "
        "after goto/login instead of right after context.new_page()"
    )


# The two shapes the real eduverse.one/th/goals page takes. The demo account
# flips from EMPTY to HAS_GOALS permanently the moment it creates its first
# goal (goals/page.tsx auto-opens the form only when the account has zero
# goals), which is exactly how the first production demo render broke: it
# succeeded once, created a goal, and every later run then timed out waiting
# for a textarea that the collapsed form no longer rendered.
GOALS_EMPTY_HTML = """<!doctype html><meta charset=utf-8>
<body><form><textarea required></textarea>
<button type=submit>สร้างเป้าหมาย</button></form></body>"""

GOALS_HAS_GOALS_HTML = """<!doctype html><meta charset=utf-8>
<body>
<button type=button>อ่านงบการเงินเป็นภายใน 3 เดือน</button>
<button type=button onclick="
  document.body.insertAdjacentHTML('beforeend',
    '<form><textarea required></textarea><button type=submit>ok</button></form>')
">ตั้งเป้าหมายกับคาวี</button>
</body>"""


@pytest.mark.slow
@pytest.mark.parametrize("html", [GOALS_EMPTY_HTML, GOALS_HAS_GOALS_HTML],
                         ids=["zero-goals-form-open", "has-goals-form-collapsed"])
def test_goals_page_selector_works_in_both_states(tmp_path, monkeypatch, html):
    """The shipped goal-to-course scenario must survive both page shapes.

    It relies on page.click() being NON-strict -- taking the first match in
    DOM order from a selector list -- so one step both opens the collapsed
    form and no-ops (focuses the textarea) when the form is already open.
    If Playwright ever makes page.click() strict, this test fails loudly
    instead of the failure surfacing as a 3am production render timeout.
    """
    import app.video.demo as demo
    from app.video.scenario import load_scenario

    monkeypatch.setattr(demo, "synthesize", _fake_synth(tmp_path))

    page = tmp_path / "goals.html"
    page.write_text(html, encoding="utf-8")

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(demo.__file__)))), "..", "scenarios")
    shipped = load_scenario("goal-to-course", os.path.normpath(root))
    open_step, type_step = shipped.steps[1], shipped.steps[2]
    assert open_step.action == "click" and type_step.action == "type"

    # Replay only the state-sensitive pair against the fixture; the rest of
    # the scenario talks to the live app and cannot run offline.
    scenario = Scenario(name="fx", login=False, steps=[open_step, type_step])
    segments = render_demo(scenario, str(tmp_path), base_url=f"file://{page}", login=None)
    assert len(segments) == 2
