import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from app.video.ffmpeg import blip_command, fit_filter, probe_duration, run, srt_from_segments
from app.video.tts import Narration

WIDTH, HEIGHT = 1080, 1920
# The render image (render/Dockerfile, Task 11) is Ubuntu 22.04 "jammy"
# (mcr.microsoft.com/playwright/python:v1.49.0-jammy) with `fonts-noto-core`
# installed via apt, which drops NotoSansThai-Regular.ttf at this exact path.
# Kept as the default candidate so production needs no extra lookup;
# _thai_font() below falls back through macOS locations and fc-match for
# local dev, where this path does not exist.
FONT = "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"
HOOK_SECONDS = 3

_MAC_THAI_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Ayuthaya.ttf",
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
    "/System/Library/Fonts/Supplemental/Tahoma.ttf",
]


@lru_cache
def _thai_font() -> str | None:
    """Resolve a Thai-capable font file, or None if none is available.

    The composer must never fail a whole render just because the local
    machine lacks the render image's font package (fonts-noto-core, Task
    11) -- the caller (compose()) skips the hook drawtext overlay, and
    derives the burned subtitle style's FontName from FONT itself instead
    (see compose()), when this returns None rather than propagating an
    FFmpegError.
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


def _font_family(path: str) -> str:
    """Family name implied by a font's filename, e.g.
    'NotoSansThai-Regular.ttf' -> 'Noto Sans Thai'.

    Sources the burned subtitle FontName from the exact font _thai_font()
    resolved, instead of a second hardcoded 'Noto Sans Thai' literal that
    only matched by coincidence in production (where _thai_font() always
    resolves FONT) and picked the wrong family -- rendering broken glyphs --
    whenever _thai_font() fell back to a non-Noto font on a dev machine.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"-(Regular|Bold|Italic|Medium|SemiBold|Light)$", "", stem)
    words = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", stem)
    return " ".join(words) if words else stem


# Zero-advance Thai combining vowel/tone marks (general category Mn):
# MAI HAN-AKAT, SARA I..SARA UU, PHINTHU, MAITAIKHU, MAI EK..YAMAKKAN. These
# attach visually to the preceding base consonant and must never be counted
# toward a line's width budget or separated from that base by a line break.
_THAI_COMBINING = frozenset(
    "ัิีึืฺุู"
    "็่้๊๋์ํ๎"
)

# Conservative advance-bearing-cluster budget per burned-subtitle line. The
# available box width is WIDTH minus the style's MarginL+MarginR (960px at
# 1080 - 60 - 60); at FontSize=60 with a Thai sans font, base clusters run
# roughly 33-37px wide, so ~26-29 fit -- 24 leaves headroom. Calibrated by
# rendering against Thonburi (the macOS dev fallback font); Noto Sans Thai,
# the render image's actual font (see FONT), isn't installed on this dev
# machine to measure against directly, so this errs conservative rather
# than exact.
_WRAP_CHARS_PER_LINE = 24


def _thai_clusters(text: str) -> list[str]:
    """Split text into user-visible clusters -- a base character plus any
    trailing zero-width Thai combining marks -- so wrapping always breaks
    between clusters, never inside one.
    """
    clusters: list[str] = []
    for ch in text:
        if clusters and ch in _THAI_COMBINING:
            clusters[-1] += ch
        else:
            clusters.append(ch)
    return clusters


def _wrap_subtitle_text(text: str, max_chars: int = _WRAP_CHARS_PER_LINE) -> str:
    """Hard-wrap `text` into "\\n"-joined lines sized to fit the burned
    subtitle's frame width.

    libass performs NO automatic word-wrap of unspaced Thai text: wrapping
    there was empirically 1 line per (space-count + 1) regardless of
    WrapStyle/MarginL/MarginR (WrapStyle=0 and WrapStyle=1 rendered
    byte-identical output; WrapStyle=2 differed only by disabling the one
    space-triggered break). Thai is conventionally written with no spaces
    between words, so a normal, single-sentence narration line -- zero
    spaces -- burned as one unbroken line that ran off both edges of the
    frame no matter how force_style's script-resolution/margins were tuned.
    The only thing that reliably stacked multiple lines within the frame was
    an actual line break in the SRT cue (ffmpeg's SRT->ASS conversion maps
    each source line to a hard "\\N", which libass always honors). So this
    wraps the text itself, upstream of libass, using a plain greedy
    word-wrap over Thai grapheme clusters (see _thai_clusters): break at the
    last space within budget if there is one, else hard-break at the
    cluster boundary.
    """
    if not text:
        return text
    lines: list[str] = []
    line: list[str] = []
    last_space_idx: int | None = None
    for cluster in _thai_clusters(text):
        line.append(cluster)
        if cluster == " ":
            last_space_idx = len(line) - 1
        if len(line) >= max_chars:
            if last_space_idx is not None:
                lines.append("".join(line[:last_space_idx]).strip())
                line = line[last_space_idx + 1:]
            else:
                lines.append("".join(line))
                line = []
            last_space_idx = None
    if line:
        lines.append("".join(line).strip())
    return "\n".join(l for l in lines if l)


def _hook_overlay(font: str | None, hook: str) -> str:
    """Build the drawtext filter fragment for the hook overlay, or "".

    No Thai font found (e.g. local macOS dev without fonts-noto-core, the
    package the render image installs) means "" — the render proceeds
    without a hook overlay rather than failing the whole compose over a
    missing font file.
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


def compose(
    segments: list[Segment], hook: str, work_dir: str, subtitles: bool = True
) -> tuple[str, str]:
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

    # The hook overlay is independent of the `subtitles` flag (see worker.py:
    # a tips card's on-screen hook headline is drawn by this same drawtext,
    # not by the burned-subtitle track), so the font is always resolved.
    font = _thai_font()

    vf_parts: list[str] = []
    if subtitles:
        srt = os.path.join(work_dir, "subs.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(
                srt_from_segments([
                    (_wrap_subtitle_text(s.narration.text), s.narration.seconds)
                    for s in segments
                ])
            )
        # No Thai font resolved anywhere (not even a macOS fallback or fc-match)
        # is unreachable in production -- FONT always exists there -- so this
        # falls back to _font_family(FONT) rather than a second literal, keeping
        # exactly one hardcoded font name in this module.
        family = _font_family(font) if font else _font_family(FONT)
        # libass interprets FontSize/Margin* against the subtitle SCRIPT's own
        # PlayResX/PlayResY, not the actual video frame size. ffmpeg's SRT ->
        # ASS conversion defaults that script resolution to the classic SSA
        # 384x288, so a style tuned by eyeballing raw numbers (FontSize=16,
        # MarginV=120) rendered wildly wrong once libass scaled it up to the
        # real 1080x1920 frame -- the subtitle drifted into the vertical
        # middle, oversized, and its opaque background box swallowed the
        # card's own text. force_style can override script-info parameters as
        # well as style parameters (documented ffmpeg `subtitles` filter
        # behavior), so PlayResX/PlayResY are pinned here to the real frame
        # size and every other value is chosen in that same coordinate space:
        # a FontSize that reads on a phone, Alignment=2 (bottom-centre), a
        # MarginV clear of the bottom edge, and MarginL/MarginR insets.
        # WrapStyle=0 is set for correctness (it governs how any pre-existing
        # line breaks combine with further auto-wrap) but does NOT by itself
        # make long lines wrap -- libass has no Thai word segmentation, so it
        # auto-wraps only at existing spaces, and an unspaced Thai sentence
        # (the normal case) has none. The actual wrap happens upstream, in
        # _wrap_subtitle_text() below, which hard-breaks the text into
        # multiple SRT lines before it ever reaches libass.
        subtitle_style = (
            f"FontName={family},FontSize=60,PrimaryColour=&H00FFFFFF,"
            f"BorderStyle=3,Outline=1,PlayResX={WIDTH},PlayResY={HEIGHT},"
            "Alignment=2,MarginV=180,MarginL=60,MarginR=60,WrapStyle=0"
        )
        sub_filter = f"subtitles='{srt}'"
        if font:
            # Point libass at the directory the resolved font actually lives in,
            # so it can find `family` above even when that family isn't
            # registered with the system's fontconfig (true of every macOS
            # fallback candidate; harmless/no-op on the render image, where
            # fontconfig already knows "Noto Sans Thai").
            sub_filter += f":fontsdir='{os.path.dirname(font)}'"
        sub_filter += f":force_style='{subtitle_style}'"
        vf_parts.append(sub_filter)

    hook_frag = _hook_overlay(font, hook)
    if hook_frag:
        vf_parts.append(hook_frag.lstrip(","))
    vf = ",".join(vf_parts)

    mp4 = os.path.join(work_dir, "final.mp4")
    cmd = ["ffmpeg", "-y", "-i", video, "-i", voice]
    if blips:
        cmd += ["-i", blips, "-filter_complex",
                "[1:a][2:a]amix=inputs=2:normalize=0,loudnorm[a]", "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-af", "loudnorm", "-map", "0:v", "-map", "1:a"]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", mp4]
    run(cmd)

    poster = os.path.join(work_dir, "poster.jpg")
    run(["ffmpeg", "-y", "-i", mp4, "-ss", "1", "-frames:v", "1", poster])
    return mp4, poster
