import os
import subprocess

import pytest

import app.video.compose as compose_mod
from app.video.compose import (
    Segment,
    _font_family,
    _hook_overlay,
    _thai_clusters,
    _wrap_subtitle_text,
    compose,
)
from app.video.ffmpeg import probe_duration
from app.video.tts import Narration


def _make_clip(path: str, seconds: float, color: str = "blue") -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c={color}:s=540x960:d={seconds}", "-pix_fmt", "yuv420p", path],
        capture_output=True, check=True,
    )
    return path


def _make_narration(path: str, seconds: float, text: str) -> Narration:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=300:duration={seconds}:sample_rate=24000", "-ac", "1", path],
        capture_output=True, check=True,
    )
    return Narration(text=text, path=path, seconds=seconds)


@pytest.mark.slow
def test_compose_produces_vertical_mp4_with_audio_and_poster(tmp_path):
    # A long line (well past what fits on one 1080-wide row at a legible
    # phone font size) exercises WrapStyle=0 wrapping, not just placement.
    long_line = (
        "นี่คือประโยคภาษาไทยที่ค่อนข้างยาวมากสำหรับทดสอบการตัดคำและ"
        "การจัดวางคำบรรยายที่เผาไว้ในวิดีโอแนวตั้งขนาดหนึ่งพันแปดสิบคูณหนึ่งพันเก้าร้อยยี่สิบพิกเซล"
    )
    segs = [
        Segment(
            clip_path=_make_clip(str(tmp_path / "a.mp4"), 6.0),
            narration=_make_narration(str(tmp_path / "a.wav"), 2.0, "สวัสดีครับ"),
            fit="speedup", sound="click",
        ),
        Segment(
            clip_path=_make_clip(str(tmp_path / "b.mp4"), 1.0, "green"),
            narration=_make_narration(str(tmp_path / "b.wav"), 3.0, long_line),
            fit="hold", sound=None,
        ),
    ]
    mp4, poster = compose(segs, hook="ทดสอบ", work_dir=str(tmp_path))

    assert os.path.exists(mp4) and os.path.exists(poster)
    # total = sum of narration durations (each clip is fitted to its narration)
    assert 4.6 < probe_duration(mp4) < 5.6

    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
         "-of", "default=nw=1", mp4],
        capture_output=True, text=True,
    ).stdout
    assert "codec_type=audio" in streams
    assert "width=1080" in streams and "height=1920" in streams

    # Regression guard for the production defect: the burned subtitle must
    # land in the BOTTOM third of the 1080x1920 frame (Alignment=2,
    # MarginV=180 in a PlayResY=1920 script), not the vertical middle it
    # shipped in when force_style was scaled against libass's default
    # 384x288 script resolution. Grab a frame from well inside the second
    # segment (subtitle text is on screen for its full 3s), crop out the
    # bottom third (y=1280..1920) and the middle third (y=640..1280), and
    # compare PNG byte sizes as a proxy for "how much non-background detail
    # is in this region": both clip backgrounds are flat colors, so a crop
    # with no subtitle content compresses to a tiny PNG, while a crop
    # containing the burned white-text-on-black-box subtitle compresses far
    # larger. If the subtitle were still mis-scaled into the vertical
    # middle, the middle crop would be the large one instead of the bottom.
    bottom_png = str(tmp_path / "bottom.png")
    middle_png = str(tmp_path / "middle.png")
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "3.5", "-i", mp4, "-vf", "crop=1080:640:0:1280",
         "-frames:v", "1", bottom_png],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "3.5", "-i", mp4, "-vf", "crop=1080:640:0:640",
         "-frames:v", "1", middle_png],
        capture_output=True, check=True,
    )
    bottom_size = os.path.getsize(bottom_png)
    middle_size = os.path.getsize(middle_png)
    assert bottom_size > middle_size * 3, (
        "expected the burned subtitle's detail (text + opaque box) to dominate "
        f"the bottom-third crop's PNG size vs. the flat-color middle third; "
        f"got bottom={bottom_size} bytes, middle={middle_size} bytes"
    )

    # Second regression guard, for the other half of the same production
    # defect: the burned subtitle must WRAP inside the frame instead of
    # running off either edge. libass performs no automatic word-wrap of
    # unspaced Thai text (confirmed empirically: WrapStyle 0 vs 1 rendered
    # byte-identical output; a normal, space-free Thai sentence burned as
    # one unbroken line bleeding past both x=0 and x=1080 no matter how
    # WrapStyle/MarginL/MarginR were tuned) -- compose() now hard-wraps the
    # text itself before handing it to libass (_wrap_subtitle_text). Crop a
    # narrow strip hugging each edge over the same bottom-third band, and
    # compare each to a same-size strip pulled from the middle third
    # (guaranteed subtitle-free, per the assertion above) as the flat-
    # background baseline. A wrapped line leaves both edge strips at
    # baseline; a clipped, unwrapped line fills them with glyph pixels and
    # inflates their PNG size several times over.
    def _crop_size(vf: str, out: str) -> int:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "3.5", "-i", mp4, "-vf", vf, "-frames:v", "1", out],
            capture_output=True, check=True,
        )
        return os.path.getsize(out)

    left_edge = _crop_size("crop=40:640:0:1280", str(tmp_path / "left_edge.png"))
    right_edge = _crop_size("crop=40:640:1040:1280", str(tmp_path / "right_edge.png"))
    left_baseline = _crop_size("crop=40:640:0:640", str(tmp_path / "left_baseline.png"))
    right_baseline = _crop_size("crop=40:640:1040:640", str(tmp_path / "right_baseline.png"))
    assert left_edge <= left_baseline * 2, (
        "expected the left frame edge to stay flat background (subtitle "
        f"wrapped inside the frame); got {left_edge} bytes vs background "
        f"baseline {left_baseline} bytes -- text may be running off the left edge"
    )
    assert right_edge <= right_baseline * 2, (
        "expected the right frame edge to stay flat background (subtitle "
        f"wrapped inside the frame); got {right_edge} bytes vs background "
        f"baseline {right_baseline} bytes -- text may be running off the right edge"
    )


def test_subtitles_false_skips_subtitles_filter(monkeypatch, tmp_path):
    # Regression test for the worker.py wiring: tips cards already render
    # their own on-screen headline/body text, so compose(subtitles=False)
    # must not add ffmpeg's `subtitles=` filter to -vf at all (the drawtext
    # hook overlay, used by both formats, is unaffected and untouched here).
    calls = []
    monkeypatch.setattr(compose_mod, "run", lambda cmd: calls.append(cmd))

    seg = Segment(
        clip_path=_make_clip(str(tmp_path / "a.mp4"), 2.0),
        narration=_make_narration(str(tmp_path / "a.wav"), 2.0, "สวัสดีครับ"),
        fit="hold", sound=None,
    )

    compose([seg], hook="ทดสอบ", work_dir=str(tmp_path), subtitles=False)

    # The final render call is the one carrying "-c:v" (video encode); the
    # earlier calls are the per-clip fit/concat steps, which never have -vf.
    render_cmds = [c for c in calls if "-c:v" in c]
    assert render_cmds, "expected the final ffmpeg render invocation to be captured"
    render_cmd = render_cmds[0]
    if "-vf" in render_cmd:
        vf_value = render_cmd[render_cmd.index("-vf") + 1]
        assert "subtitles=" not in vf_value
    # subtitles=False must skip the .srt write entirely, not just the filter.
    assert not os.path.exists(os.path.join(str(tmp_path), "subs.srt"))


@pytest.mark.slow
def test_subtitles_false_renders_real_video_with_hook_and_no_srt_filter(tmp_path):
    # The mocked-`run` test above proves the -vf string is well-formed; this
    # exercises the actual, unmocked ffmpeg invocation for that same
    # subtitles=False path (the one every "tips" render takes in
    # production) with a non-empty hook, so `-vf` starts with `drawtext=`
    # (via hook_frag.lstrip(",")) instead of `subtitles=`. If that chain
    # were malformed, every tips render would fail in production.
    seg = Segment(
        clip_path=_make_clip(str(tmp_path / "a.mp4"), 2.0),
        narration=_make_narration(str(tmp_path / "a.wav"), 2.0, "สวัสดีครับ"),
        fit="hold", sound=None,
    )

    mp4, poster = compose([seg], hook="ทดสอบ", work_dir=str(tmp_path), subtitles=False)

    assert os.path.exists(mp4) and os.path.getsize(mp4) > 0
    assert os.path.exists(poster) and os.path.getsize(poster) > 0
    assert not os.path.exists(str(tmp_path / "subs.srt"))


def test_thai_combining_set_is_exactly_the_16_expected_codepoints():
    # A missing codepoint here would make the orphaned-mark assertion in
    # test_wrap_subtitle_text_hard_breaks_unspaced_run_without_orphaning_marks
    # pass vacuously (the "mark" would just form its own ordinary cluster and
    # never trip the check) -- pin the exact codepoint set so that failure
    # mode can't hide. MAI HAN-AKAT (0E31), SARA I..SARA UU + PHINTHU
    # (0E34-0E3A), MAITAIKHU..YAMAKKAN (0E47-0E4E).
    expected = {0x0E31} | set(range(0x0E34, 0x0E3B)) | set(range(0x0E47, 0x0E4F))
    actual = {ord(c) for c in compose_mod._THAI_COMBINING}
    assert actual == expected
    assert len(compose_mod._THAI_COMBINING) == 16  # no duplicate silently shrank the set


def test_thai_clusters_keeps_combining_marks_attached_to_their_base():
    # "อัตโนมัติ" contains two MAI HAN-AKAT (U+0E31) marks, one on อ+ั and one
    # on ต+ั. Splitting naively on len() would separate a mark from its base;
    # clustering must keep each mark glued to the character before it.
    clusters = _thai_clusters("อัตโนมัติ")
    assert "".join(clusters) == "อัตโนมัติ"
    # No cluster may start with a combining mark -- that would mean it got
    # split off from the base character it attaches to.
    assert all(c[0] not in compose_mod._THAI_COMBINING for c in clusters)
    # อ + ั (MAI HAN-AKAT) and ม + ั fold into one cluster each; โ (SARA O,
    # U+0E42) has its own normal advance width (it's a leading vowel sign,
    # not a zero-width combining mark) so it starts its own cluster.
    assert clusters == ["อั", "ต", "โ", "น", "มั", "ติ"]


def test_wrap_subtitle_text_leaves_short_text_untouched():
    assert _wrap_subtitle_text("สวัสดีครับ") == "สวัสดีครับ"
    assert _wrap_subtitle_text("") == ""


def test_wrap_subtitle_text_breaks_at_a_space_within_budget():
    # Two words that together exceed the budget but each fit individually --
    # the break must land on the space, not mid-word.
    text = "การตลาดออนไลน์ในยุคนี้ ต้องอาศัยความเร็ว"
    wrapped = _wrap_subtitle_text(text, max_chars=24)
    lines = wrapped.split("\n")
    assert len(lines) == 2
    assert lines[0] == "การตลาดออนไลน์ในยุคนี้"
    assert lines[1] == "ต้องอาศัยความเร็ว"


def test_wrap_subtitle_text_hard_breaks_unspaced_run_without_orphaning_marks():
    # A run with no spaces at all -- the realistic case for a single Thai
    # sentence -- must still wrap (this is the shipped defect: unspaced text
    # burned as one line that ran off both edges), and no line may start
    # with a combining mark (that would mean it got orphaned from its base).
    text = "การตลาดออนไลน์ในยุคนี้ต้องอาศัยทั้งความเร็วและความแม่นยำ" * 2
    wrapped = _wrap_subtitle_text(text, max_chars=24)
    lines = wrapped.split("\n")
    assert len(lines) > 1
    for line in lines:
        assert line, "wrapping must not produce an empty line"
        assert line[0] not in compose_mod._THAI_COMBINING
        assert len(_thai_clusters(line)) <= 24


def test_hook_overlay_skipped_when_no_thai_font_available():
    # The render image's fonts-noto-core install has NotoSansThai; a local
    # machine without any Thai font must not crash the whole compose over a
    # missing drawtext font file.
    assert _hook_overlay(font=None, hook="ทดสอบ", work_dir="/nonexistent") == ""


def test_hook_overlay_skipped_when_hook_is_empty():
    assert _hook_overlay(font="/some/font.ttf", hook="", work_dir="/nonexistent") == ""


def test_hook_overlay_uses_resolved_font_path(tmp_path):
    frag = _hook_overlay(font="/some/font.ttf", hook="ทดสอบ", work_dir=str(tmp_path))
    assert "drawtext=fontfile=/some/font.ttf" in frag
    # The hook now goes through textfile= rather than text=: drawtext cannot
    # wrap, and a newline inside a filter-graph string terminates the option.
    assert f"textfile={tmp_path}/hook.txt" in frag
    assert (tmp_path / "hook.txt").read_text(encoding="utf-8") == "ทดสอบ"


def test_hook_overlay_wraps_a_long_hook_and_never_starts_off_screen(tmp_path):
    """A long Thai hook must be wrapped, not centred off the frame.

    drawtext cannot wrap. A shipped tips video carried a 44-character hook at
    fontsize 64 -- roughly 1500px against a 1080px frame -- so `(w-text_w)/2`
    evaluated negative and the headline ran off both edges with its opening
    characters cut away.
    """
    hook = "ท่องศัพท์เท่าไหร่ก็ลืม ลองเปลี่ยนมาจำแบบนี้ดู"
    frag = _hook_overlay(font="/some/font.ttf", hook=hook, work_dir=str(tmp_path))

    lines = (tmp_path / "hook.txt").read_text(encoding="utf-8").split("\n")
    assert len(lines) > 1, "a 44-character hook must wrap onto multiple lines"
    for line in lines:
        assert len(_thai_clusters(line)) <= compose_mod._HOOK_CHARS_PER_LINE
    # Nothing may be dropped by wrapping.
    assert "".join(lines).replace(" ", "") == hook.replace(" ", "")
    # And the x expression itself cannot resolve negative.
    assert "x=max(0" in frag


def test_font_family_derives_noto_sans_thai_from_the_render_image_filename():
    # This is the literal that used to be hardcoded a second time in the
    # subtitle force_style -- pinning it here documents that sourcing
    # FontName from _font_family(FONT) is a genuine no-op in production.
    assert _font_family(compose_mod.FONT) == "Noto Sans Thai"


def test_font_family_derives_single_word_names():
    assert _font_family("/System/Library/Fonts/Supplemental/Thonburi.ttc") == "Thonburi"
    assert _font_family("/System/Library/Fonts/Supplemental/Ayuthaya.ttf") == "Ayuthaya"


def test_mac_candidates_are_absolute_font_paths():
    # A typo like a wrong extension (the shipped bug: Ayuthaya.ttc instead
    # of the real Ayuthaya.ttf) doesn't crash _thai_font() -- it silently
    # falls through to the next candidate, which is exactly why the old
    # "font is None or os.path.exists(font)" test never caught it. This
    # checks the candidate list's own shape instead.
    for path in compose_mod._MAC_THAI_FONT_CANDIDATES:
        assert os.path.isabs(path)
        assert path.endswith((".ttf", ".ttc", ".otf"))


def test_thai_font_returns_first_existing_candidate(monkeypatch, tmp_path):
    real_font = tmp_path / "SomeThaiFont.ttf"
    real_font.write_bytes(b"")
    monkeypatch.setattr(compose_mod, "FONT", str(tmp_path / "missing-render-image-font.ttf"))
    monkeypatch.setattr(
        compose_mod, "_MAC_THAI_FONT_CANDIDATES",
        [str(tmp_path / "also-missing.ttf"), str(real_font)],
    )
    compose_mod._thai_font.cache_clear()
    try:
        assert compose_mod._thai_font() == str(real_font)
    finally:
        compose_mod._thai_font.cache_clear()


def test_thai_font_falls_through_to_none_when_nothing_resolves(monkeypatch, tmp_path):
    monkeypatch.setattr(compose_mod, "FONT", str(tmp_path / "missing-render-image-font.ttf"))
    monkeypatch.setattr(
        compose_mod, "_MAC_THAI_FONT_CANDIDATES",
        [str(tmp_path / "a.ttf"), str(tmp_path / "b.ttc")],
    )
    monkeypatch.setattr(compose_mod.shutil, "which", lambda name: None)
    compose_mod._thai_font.cache_clear()
    try:
        assert compose_mod._thai_font() is None
    finally:
        compose_mod._thai_font.cache_clear()


@pytest.mark.slow
def test_output_audio_is_48khz_not_loudnorm_192k(tmp_path):
    """loudnorm resamples to 192kHz and emits at that rate; AAC then clamps
    to its own 96kHz ceiling. Without an explicit -ar the factory ships
    96kHz audio built from a 24kHz TTS source -- off the standard rates
    platforms expect, for zero added information.
    """
    segs = [Segment(
        clip_path=_make_clip(str(tmp_path / "c.mp4"), 2.0),
        narration=_make_narration(str(tmp_path / "c.wav"), 1.5, "ทดสอบเสียง"),
        fit="speedup", sound=None,
    )]
    mp4, _ = compose(segs, hook=None, work_dir=str(tmp_path), subtitles=False)

    rate = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate", "-of", "csv=p=0", mp4],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert rate == "48000", f"expected 48000 Hz audio, got {rate} Hz"
