import os
import re
import subprocess

import pytest

from app.strategy import MusicConfig, Strategy
from app.video.ffmpeg import probe_duration
from app.video.music import available_tracks, make_bed, pick_track


def _fake_track(root: str, name: str, seconds: float = 8.0) -> str:
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"{name}.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=220:duration={seconds}:sample_rate=44100",
         "-ac", "2", path],
        capture_output=True, check=True,
    )
    return path


def _mean_volume(path: str) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", proc.stderr)
    assert m, f"volumedetect produced no mean_volume for {path}"
    return float(m.group(1))


def test_no_tracks_configured_means_no_music(tmp_path):
    assert pick_track([], "item-1", str(tmp_path)) is None


def test_track_named_but_missing_from_disk_degrades_to_no_music(tmp_path):
    """Music is a polish layer. A track named in strategy.yaml but absent
    from the image must yield a silent-of-music video, never a failed render
    -- losing the bed is not worth dropping a finished video on the floor.
    """
    assert pick_track(["not-in-image"], "item-1", str(tmp_path)) is None


def test_pick_is_stable_for_the_same_item(tmp_path):
    """Re-rendering an item after a fix must keep the music it already had,
    or the soundtrack silently changes under a reviewer who already approved
    how it sounded.
    """
    for name in ("city-sunshine", "funshine", "motions"):
        _fake_track(str(tmp_path), name, seconds=1.0)
    ids = ["city-sunshine", "funshine", "motions"]
    first = pick_track(ids, "item-abc", str(tmp_path))
    assert first is not None
    assert all(pick_track(ids, "item-abc", str(tmp_path)) == first for _ in range(5))


def test_different_items_spread_across_the_mood_list(tmp_path):
    """Every post carrying identical audio reads as templated, which is the
    whole reason the config takes a list rather than one track.
    """
    for name in ("city-sunshine", "funshine", "motions"):
        _fake_track(str(tmp_path), name, seconds=1.0)
    ids = ["city-sunshine", "funshine", "motions"]
    chosen = {pick_track(ids, f"item-{i}", str(tmp_path)) for i in range(40)}
    assert len(chosen) == 3, f"expected all 3 tracks to be used, got {chosen}"


@pytest.mark.parametrize("bad", ["../secrets", "a/b", "UPPER", "", "-lead", "trail-"])
def test_malformed_track_ids_are_rejected_not_resolved(tmp_path, bad):
    """Track ids become filenames. They come from our own config rather than
    user input, but a typo containing a slash must fail as "no such track"
    and never resolve outside the music directory.
    """
    assert available_tracks([bad], str(tmp_path)) == []


def test_strategy_without_a_music_block_is_still_valid():
    """Shipping without music is the pre-feature behaviour and has to stay a
    valid configuration -- otherwise this change breaks every existing
    strategy.yaml.
    """
    s = Strategy(voice="v", audiences=["a"], banned_words=[], platform_notes={})
    assert s.music.for_format("tips") == []
    assert s.music.gain_lufs == -33.0


def test_music_config_maps_formats_and_ignores_unknown_ones():
    cfg = MusicConfig(tips=["a"], demo=["b"])
    assert cfg.for_format("tips") == ["a"]
    assert cfg.for_format("demo") == ["b"]
    assert cfg.for_format("motion_ad") == []


@pytest.mark.slow
def test_bed_is_cut_to_length_and_pushed_well_below_the_source(tmp_path):
    track = _fake_track(str(tmp_path), "loud", seconds=8.0)
    bed = make_bed(track, 4.0, str(tmp_path), lufs=-33.0)

    assert probe_duration(bed) == pytest.approx(4.0, abs=0.15)
    assert _mean_volume(bed) < _mean_volume(track) - 10, (
        "the bed must sit far below the raw track, or it competes with the "
        "Thai narration instead of sitting under it"
    )


@pytest.mark.slow
def test_bed_loops_a_track_shorter_than_the_video(tmp_path):
    """A track shorter than the video must loop, not leave the back half of
    the video silent.
    """
    track = _fake_track(str(tmp_path), "short", seconds=2.0)
    bed = make_bed(track, 6.0, str(tmp_path), lufs=-33.0)
    assert probe_duration(bed) == pytest.approx(6.0, abs=0.15)


@pytest.mark.slow
def test_compose_actually_mixes_the_bed_into_the_output(tmp_path):
    """The load-bearing assertion for the whole feature: with a silent
    narration, the finished video carries audible energy ONLY if the bed
    reached the mix. Asserting the file merely exists would pass even if the
    music input were dropped from the filtergraph.
    """
    from app.video.compose import Segment, compose
    from app.video.tts import Narration

    clip = str(tmp_path / "clip.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=540x960:d=4",
         "-pix_fmt", "yuv420p", clip],
        capture_output=True, check=True,
    )
    silent = str(tmp_path / "silent.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", "3", silent],
        capture_output=True, check=True,
    )
    seg = Segment(clip_path=clip, narration=Narration(text="", path=silent, seconds=3.0),
                  fit="speedup", sound=None)
    track = _fake_track(str(tmp_path), "bed-src", seconds=8.0)

    quiet, _ = compose([seg], hook=None, work_dir=str(tmp_path / "off"), subtitles=False)
    scored, _ = compose([seg], hook=None, work_dir=str(tmp_path / "on"), subtitles=False,
                        music_track=track)

    assert _mean_volume(scored) > _mean_volume(quiet) + 20, (
        "output with a music track is not measurably louder than without one "
        "-- the bed never made it into the mix"
    )


@pytest.mark.slow
def test_music_survives_alongside_ui_blips(tmp_path):
    """The demo path mixes THREE audio sources -- narration, UI blips, and
    music. That is the case a hard-coded "[1:a][2:a]" amix label list breaks:
    it drops whichever bed lands at input 3, silently, in exactly the format
    that ships to social. The two-input case cannot catch it.
    """
    from app.video.compose import Segment, compose
    from app.video.tts import Narration

    clip = str(tmp_path / "clip.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=540x960:d=4",
         "-pix_fmt", "yuv420p", clip],
        capture_output=True, check=True,
    )
    silent = str(tmp_path / "silent.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "3", silent],
        capture_output=True, check=True,
    )
    # sound="click" is what puts a blip track into the mix, making music the
    # third input rather than the second.
    seg = Segment(clip_path=clip, narration=Narration(text="", path=silent, seconds=3.0),
                  fit="speedup", sound="click")
    track = _fake_track(str(tmp_path), "three-way", seconds=8.0)

    blips_only, _ = compose([seg], hook=None, work_dir=str(tmp_path / "two"),
                            subtitles=False)
    with_music, _ = compose([seg], hook=None, work_dir=str(tmp_path / "three"),
                            subtitles=False, music_track=track)

    assert probe_duration(with_music) == pytest.approx(3.0, abs=0.3)
    # Compare the two mixes rather than asserting the output is simply "not
    # silent": the blips alone clear any absolute floor, so a floor check
    # passes even when the music input is dropped -- verified by mutating the
    # label list back to a hard-coded "[1:a][2:a]". Blips are short
    # transients with silence between them; a continuous bed lifts the mean
    # by ~5dB even after the final loudnorm.
    assert _mean_volume(with_music) > _mean_volume(blips_only) + 3, (
        "adding music to a mix that already has UI blips did not raise the "
        "mean level -- the bed was dropped from the filtergraph"
    )
