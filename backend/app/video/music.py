"""CC0 background-music beds.

Tracks come from AIVDO's public FreePD library (see docs/MUSIC.md) and are
baked into the render image at BUILD time by render/fetch_music.py, so a
render never depends on a third-party host being reachable.

The mix level follows AIVDO's Motion Ad recipe: normalise the bed to a very
low absolute loudness (-33 LUFS) BEFORE mixing, so it sits under the Thai
narration rather than competing with it. The final loudnorm in compose()
then brings the summed mix up to broadcast level, preserving that ratio.
"""

import hashlib
import os
import re

from app.video.ffmpeg import run

MUSIC_ROOT = os.environ.get("MUSIC_ROOT", "./music")

# Track ids become filenames, so they are constrained rather than trusted.
# They come from strategy.yaml (our own config, not user input), but a typo
# with a slash in it should fail as "no such track" and never escape the
# music directory.
_TRACK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$")


def available_tracks(track_ids: list[str], root: str = MUSIC_ROOT) -> list[str]:
    """The subset of `track_ids` that are well-formed AND present on disk.

    A track named in strategy.yaml but missing from the image must degrade to
    "this video has no music", never to a failed render -- music is a polish
    layer, and losing it is not worth dropping a finished video on the floor.
    """
    return [
        t for t in track_ids
        if _TRACK_ID.match(t) and os.path.isfile(os.path.join(root, f"{t}.mp3"))
    ]


def pick_track(track_ids: list[str], key: str, root: str = MUSIC_ROOT) -> str | None:
    """Choose one track for `key`, or None if none are usable.

    Deterministic in `key` (the content item's id) for two reasons: re-rendering
    an item after a fix keeps the music it already had instead of silently
    swapping the soundtrack under a reviewer, and picking by hash rather than
    at random still spreads different items across the whole mood list -- so
    the feed doesn't carry identical audio on every post, which reads as
    templated.
    """
    usable = available_tracks(track_ids, root)
    if not usable:
        return None
    index = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(usable)
    return os.path.join(root, f"{usable[index]}.mp3")


def pick_track_id(track_ids: list[str], key: str) -> str | None:
    """Choose one track ID for `key`, without touching the filesystem.

    Deliberately NOT pick_track. For the motion_ad format we hand a track ID
    to AIVDO, which renders the bed on its side -- the mp3 never needs to
    exist locally, and render/fetch_music.py does not download these. Routing
    this through pick_track would fail its os.path.isfile check, return None,
    and silently ship every ad with the template's default bed.

    Same deterministic hashing as pick_track, for the same reasons: a
    re-render keeps the track a reviewer already approved, while different
    items still spread across the configured list.
    """
    usable = [t for t in track_ids if _TRACK_ID.match(t)]
    if not usable:
        return None
    index = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(usable)
    return usable[index]


def make_bed(track_path: str, seconds: float, work_dir: str,
             lufs: float = -33.0, fade: float = 1.2) -> str:
    """Render `track_path` into a bed exactly `seconds` long.

    -stream_loop -1 comes BEFORE -i on purpose: it loops the input so a track
    shorter than the video still covers it. Today's library tracks all run
    minutes and our videos run seconds, so it never engages -- it is here so
    that adding a short track later cannot produce a video whose music stops
    halfway through.

    The fades matter more than they look: without them the bed starts and
    ends on a hard cut, which is audible and cheap-sounding precisely at the
    two moments a viewer is deciding whether to keep watching. loudnorm runs
    first so the fades are not flattened back out by normalisation.
    """
    out = os.path.join(work_dir, "bed.wav")
    fade = max(0.0, min(fade, seconds / 2))
    filters = f"loudnorm=I={lufs}:TP=-4"
    if fade > 0:
        filters += f",afade=t=in:st=0:d={fade:.3f}"
        filters += f",afade=t=out:st={max(0.0, seconds - fade):.3f}:d={fade:.3f}"
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", track_path,
         "-t", f"{seconds:.3f}", "-af", filters,
         "-ar", "44100", "-ac", "2", out])
    return out
