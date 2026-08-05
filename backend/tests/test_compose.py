import os
import subprocess

import pytest

import app.video.compose as compose_mod
from app.video.compose import Segment, _font_family, _hook_overlay, compose
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
    segs = [
        Segment(
            clip_path=_make_clip(str(tmp_path / "a.mp4"), 6.0),
            narration=_make_narration(str(tmp_path / "a.wav"), 2.0, "สวัสดีครับ"),
            fit="speedup", sound="click",
        ),
        Segment(
            clip_path=_make_clip(str(tmp_path / "b.mp4"), 1.0, "green"),
            narration=_make_narration(str(tmp_path / "b.wav"), 3.0, "ลองใช้ดูครับ"),
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


def test_hook_overlay_skipped_when_no_thai_font_available():
    # The render image's fonts-noto-core install has NotoSansThai; a local
    # machine without any Thai font must not crash the whole compose over a
    # missing drawtext font file.
    assert _hook_overlay(font=None, hook="ทดสอบ") == ""


def test_hook_overlay_skipped_when_hook_is_empty():
    assert _hook_overlay(font="/some/font.ttf", hook="") == ""


def test_hook_overlay_uses_resolved_font_path():
    frag = _hook_overlay(font="/some/font.ttf", hook="ทดสอบ")
    assert "drawtext=fontfile=/some/font.ttf" in frag
    assert "text='ทดสอบ'" in frag


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
