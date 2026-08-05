import pytest

from app.video.ffmpeg import FFmpegError, blip_command, fit_filter, run, srt_from_segments


def test_srt_uses_measured_durations():
    out = srt_from_segments([("สวัสดี", 1.5), ("ครับ", 2.0)])
    assert "00:00:00,000 --> 00:00:01,500" in out
    assert "00:00:01,500 --> 00:00:03,500" in out
    assert "สวัสดี" in out and "ครับ" in out
    assert out.startswith("1\n")


def test_fit_speedup_compresses_long_clip():
    f = fit_filter(clip_seconds=60.0, target_seconds=4.0, mode="speedup")
    assert "setpts=" in f
    # 4/60 of original timestamps
    assert "0.0666" in f or "0.067" in f


def test_fit_tail_trims_to_last_window():
    f = fit_filter(clip_seconds=60.0, target_seconds=4.0, mode="tail")
    assert "trim=start=56" in f


def test_fit_hold_pads_short_clip():
    f = fit_filter(clip_seconds=2.0, target_seconds=5.0, mode="hold")
    assert "tpad=stop_duration=3" in f


def test_short_clip_never_speeds_up():
    # a 2s clip with a 5s narration must hold, not stretch weirdly
    f = fit_filter(clip_seconds=2.0, target_seconds=5.0, mode="speedup")
    assert "tpad=stop_duration=3" in f


def test_blip_command_synthesizes_audio_without_asset_files():
    cmd = blip_command("click", "/tmp/click.wav")
    assert cmd[0] == "ffmpeg"
    assert any("sine=" in part for part in cmd)
    assert cmd[-1] == "/tmp/click.wav"


def test_run_raises_with_stderr_tail():
    with pytest.raises(FFmpegError) as exc:
        run(["ffmpeg", "-i", "/nonexistent/file.mp4", "-f", "null", "-"])
    assert "nonexistent" in str(exc.value).lower() or "no such file" in str(exc.value).lower()
