import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from app.video.ffmpeg import blip_command, fit_filter, probe_duration, run, srt_from_segments
from app.video.tts import Narration

WIDTH, HEIGHT = 1080, 1920
# The render image (Debian, Task 9) installs fonts-noto-thai at this exact
# path. Kept as the default candidate so production needs no extra lookup;
# _thai_font() below falls back through macOS locations and fc-match for
# local dev, where this path does not exist.
FONT = "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"
HOOK_SECONDS = 3

_MAC_THAI_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Ayuthaya.ttc",
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
    "/System/Library/Fonts/Supplemental/Tahoma.ttf",
]


@lru_cache
def _thai_font() -> str | None:
    """Resolve a Thai-capable font file, or None if none is available.

    The composer must never fail a whole render just because the local
    machine lacks the Debian render image's font package — the caller
    (compose()) skips the hook drawtext overlay entirely when this
    returns None rather than propagating an FFmpegError.
    """
    if os.path.exists(FONT):
        return FONT
    for candidate in _MAC_THAI_FONT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    if shutil.which("fc-match"):
        try:
            proc = subprocess.run(
                ["fc-match", "-f", "%{file}", ":lang=th"],
                capture_output=True, text=True, timeout=5,
            )
            path = proc.stdout.strip()
            if proc.returncode == 0 and path and os.path.exists(path):
                return path
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _hook_overlay(font: str | None, hook: str) -> str:
    """Build the drawtext filter fragment for the hook overlay, or "".

    No Thai font found (e.g. local macOS dev without fonts-noto-thai) means
    "" — the render proceeds without a hook overlay rather than failing the
    whole compose over a missing font file.
    """
    if not hook or not font:
        return ""
    safe = hook.replace("'", "").replace(":", " ")
    return (
        f",drawtext=fontfile={font}:text='{safe}':fontcolor=white:fontsize=64:"
        f"box=1:boxcolor=black@0.55:boxborderw=24:x=(w-text_w)/2:y=220:"
        f"enable='lt(t,{HOOK_SECONDS})'"
    )


@dataclass
class Segment:
    clip_path: str
    narration: Narration
    fit: str = "speedup"
    sound: str | None = None


def _fit_clip(seg: Segment, out_path: str) -> None:
    vf = ",".join([
        fit_filter(probe_duration(seg.clip_path), seg.narration.seconds, seg.fit),
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase",
        f"crop={WIDTH}:{HEIGHT}",
        "fps=30",
    ])
    run(["ffmpeg", "-y", "-i", seg.clip_path, "-filter:v", vf, "-an",
         "-t", f"{seg.narration.seconds}", "-pix_fmt", "yuv420p", out_path])


def _concat(paths: list[str], list_path: str, out_path: str, codec_copy: bool) -> None:
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path]
    cmd += ["-c", "copy"] if codec_copy else ["-pix_fmt", "yuv420p"]
    cmd += [out_path]
    run(cmd)


def _sound_track(segments: list[Segment], work_dir: str, total: float) -> str | None:
    """Mix each step's blip at that step's start time. Returns a wav path."""
    marks = []
    clock = 0.0
    for seg in segments:
        if seg.sound:
            marks.append((seg.sound, clock))
        clock += seg.narration.seconds
    if not marks:
        return None

    inputs, filters = [], []
    for i, (kind, at) in enumerate(marks):
        blip = os.path.join(work_dir, f"blip_{i}.wav")
        run(blip_command(kind, blip))
        inputs += ["-i", blip]
        filters.append(f"[{i}:a]adelay={int(at * 1000)}|{int(at * 1000)}[b{i}]")
    mix = "".join(f"[b{i}]" for i in range(len(marks)))
    graph = ";".join(filters) + f";{mix}amix=inputs={len(marks)}:normalize=0[out]"
    out = os.path.join(work_dir, "blips.wav")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
         "-t", f"{total}", out])
    return out


def compose(segments: list[Segment], hook: str, work_dir: str) -> tuple[str, str]:
    os.makedirs(work_dir, exist_ok=True)

    fitted = []
    for i, seg in enumerate(segments):
        out = os.path.join(work_dir, f"fit_{i}.mp4")
        _fit_clip(seg, out)
        fitted.append(out)
    video = os.path.join(work_dir, "video.mp4")
    _concat(fitted, os.path.join(work_dir, "clips.txt"), video, codec_copy=False)

    voice_paths = [s.narration.path for s in segments]
    voice = os.path.join(work_dir, "voice.wav")
    _concat(voice_paths, os.path.join(work_dir, "voice.txt"), voice, codec_copy=False)

    total = sum(s.narration.seconds for s in segments)
    blips = _sound_track(segments, work_dir, total)

    srt = os.path.join(work_dir, "subs.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write(srt_from_segments([(s.narration.text, s.narration.seconds) for s in segments]))

    subtitle_style = (
        "FontName=Noto Sans Thai,FontSize=16,PrimaryColour=&H00FFFFFF,"
        "BorderStyle=3,Outline=1,MarginV=120"
    )
    vf = f"subtitles='{srt}':force_style='{subtitle_style}'"
    vf += _hook_overlay(_thai_font(), hook)

    mp4 = os.path.join(work_dir, "final.mp4")
    cmd = ["ffmpeg", "-y", "-i", video, "-i", voice]
    if blips:
        cmd += ["-i", blips, "-filter_complex",
                "[1:a][2:a]amix=inputs=2:normalize=0,loudnorm[a]", "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-af", "loudnorm", "-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", mp4]
    run(cmd)

    poster = os.path.join(work_dir, "poster.jpg")
    run(["ffmpeg", "-y", "-i", mp4, "-ss", "1", "-frames:v", "1", poster])
    return mp4, poster
