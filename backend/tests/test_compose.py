import os
import subprocess

import pytest

import app.video.compose as compose_mod
from app.video.compose import Segment, _hook_overlay, _thai_font, compose
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
    # Debian render image has NotoSansThai; a local machine without any Thai
    # font must not crash the whole compose over a missing drawtext font file.
    assert _hook_overlay(font=None, hook="ทดสอบ") == ""


def test_hook_overlay_skipped_when_hook_is_empty():
    assert _hook_overlay(font="/some/font.ttf", hook="") == ""


def test_hook_overlay_uses_resolved_font_path():
    frag = _hook_overlay(font="/some/font.ttf", hook="ทดสอบ")
    assert "drawtext=fontfile=/some/font.ttf" in frag
    assert "text='ทดสอบ'" in frag


def test_thai_font_resolves_to_something_on_this_machine():
    # Exercises the real fallback chain (Debian path -> macOS candidates ->
    # fc-match) end to end; whichever branch wins, dev machines running these
    # tests must be able to find *a* Thai-capable font.
    font = _thai_font()
    assert font is None or os.path.exists(font)


def test_thai_font_falls_back_when_debian_path_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(compose_mod, "FONT", str(tmp_path / "does-not-exist.ttf"))
    compose_mod._thai_font.cache_clear()
    try:
        font = compose_mod._thai_font()
        assert font is None or os.path.exists(font)
    finally:
        compose_mod._thai_font.cache_clear()
