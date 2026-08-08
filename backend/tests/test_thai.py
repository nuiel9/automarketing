"""Thai line-breaking, pinned against the defects that shipped.

Each test below names a real frame from a rendered video, not a hypothetical.
"""

import pytest

from app.video.thai import ZWSP, width, with_break_hints, words, wrap


def test_repetition_mark_never_starts_a_line():
    """`ๆ` attaches to the word before it.

    A shipped demo subtitle read `...ให้เป็นขั้น` / `ๆ` -- the repetition mark
    alone on a third line. The segmenter genuinely emits `ขั้น` + `ๆ` as
    separate tokens, so wrapping on raw token boundaries reproduces the bug;
    the merge rule is what prevents it.
    """
    assert words("ให้เป็นขั้นๆ")[-1] == "ขั้นๆ"
    for line in wrap("พี่กวีทักกลับทันที พร้อมวางแผนการเรียนให้เป็นขั้นๆ", 24):
        assert line != "ๆ"
        assert not line.startswith("ๆ")


def test_words_are_not_split_in_half():
    """The tips-card defect: `กลุ่มคำ` shipped as `ก` + `ลุ่มคำ`."""
    chunks = words("จำศัพท์เป็นกลุ่มคำ ความหมายคล้าย")
    assert "กลุ่ม" in chunks
    assert not any(c == "ก" for c in chunks), f"`กลุ่ม` was split: {chunks}"


def test_wrap_prefers_a_space_over_a_word_boundary():
    """Both are legal breaks; a phrase boundary reads better."""
    lines = wrap("การตลาดออนไลน์ในยุคนี้ ต้องอาศัยความเร็ว", 24)
    assert lines == ["การตลาดออนไลน์ในยุคนี้", "ต้องอาศัยความเร็ว"]


def test_wrap_respects_the_budget_and_loses_nothing():
    text = "ท่องศัพท์เท่าไหร่ก็ลืม ลองเปลี่ยนมาจำแบบนี้ดู"
    lines = wrap(text, 20)
    assert len(lines) > 1
    for line in lines:
        assert width(line) <= 20
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")


def test_wrap_handles_an_unspaced_run_longer_than_the_budget():
    text = "การตลาดออนไลน์ในยุคนี้ต้องอาศัยทั้งความเร็วและความแม่นยำ" * 2
    lines = wrap(text, 24)
    assert len(lines) > 1
    for line in lines:
        assert line.strip(), "wrapping must not emit an empty line"
        assert width(line) <= 24


@pytest.mark.parametrize("text", ["", "   "])
def test_wrap_of_blank_text_is_empty(text):
    assert wrap(text, 24) == []


def test_short_text_is_left_alone():
    assert wrap("สวัสดีครับ", 24) == ["สวัสดีครับ"]
    assert with_break_hints("สวัสดี") == "สวัสดี"


def test_break_hints_are_invisible_and_only_at_word_boundaries():
    """The browser must be able to break ONLY where Thai words end.

    Chromium segments Thai correctly on macOS but not in the render image, so
    the cards cannot rely on it -- these hints are what make the layout the
    same in both.
    """
    text = "จำศัพท์เป็นกลุ่มคำ"
    hinted = with_break_hints(text)
    assert ZWSP in hinted
    assert hinted.replace(ZWSP, "") == text, "hints must not alter the text"
    # A hint inside `กลุ่ม` would let the browser split it again.
    assert f"กลุ่ม{ZWSP}คำ" in hinted
    assert f"ก{ZWSP}ลุ่ม" not in hinted


def test_segmentation_failure_degrades_instead_of_raising(monkeypatch):
    """Line-breaking must never fail a render.

    If the tokenizer is unavailable or throws, the text still goes out -- as
    one unbroken chunk, which is the pre-segmentation behaviour -- rather than
    taking down a video that is otherwise finished.
    """
    import app.video.thai as thai_mod

    def _boom(*a, **k):
        raise RuntimeError("dictionary unavailable")

    monkeypatch.setattr(thai_mod, "_tokenizer", lambda: _boom)
    assert words("จำศัพท์เป็นกลุ่มคำ") == ["จำศัพท์เป็นกลุ่มคำ"]
    assert wrap("จำศัพท์เป็นกลุ่มคำ", 24) == ["จำศัพท์เป็นกลุ่มคำ"]
