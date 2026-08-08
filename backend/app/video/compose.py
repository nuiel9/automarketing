import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from app.video import thai
from app.video.ffmpeg import blip_command, fit_filter, probe_duration, run, srt_from_segments
from app.video.music import make_bed
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

# Ordered by preference for drawtext, which has no font-fallback chain.
# Garuda/Waree (fonts-thai-tlwg) are Thai sans faces that ALSO carry Latin and
# digits; the Noto Thai faces in the image do not (101 cmap entries, Thai
# only). FreeSerif is the last resort: it covers both scripts but is a serif,
# which sits oddly against the cards' sans -- better than losing the brand
# name, worse than Garuda.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
    "/usr/share/fonts/truetype/tlwg/Waree.ttf",
    FONT,
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
]

_MAC_THAI_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Ayuthaya.ttf",
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
    "/System/Library/Fonts/Supplemental/Tahoma.ttf",
]


@lru_cache
def _thai_font() -> str | None:
    """Resolve a font that can draw our copy, or None if none is available.

    "Thai-capable" is not enough. Our copy mixes Thai with Latin and digits --
    "Eduverse One", "AI", "3 เดือน" -- and drawtext takes ONE fontfile with no
    fallback chain. Every Noto Thai face in the render image covers Thai ONLY:
    NotoSansThai-Regular has 101 cmap entries, with no Latin letters and no
    digits (surveyed inside the image, 2026-08-09). Picking it means the brand
    name and every number either render as tofu or, once unrenderable
    characters are stripped, vanish from the hook entirely.

    So prefer a face that covers Thai AND Latin AND digits, and fall back to a
    Thai-only face only if nothing better exists -- a hook missing its Latin
    is still better than no hook at all.

    Returning None (no Thai font anywhere, e.g. a bare dev machine) is also
    supported: compose() then skips the drawtext overlay rather than failing
    the whole render over a missing font file.
    """
    thai_only: str | None = None
    for candidate in _FONT_CANDIDATES + _MAC_THAI_FONT_CANDIDATES:
        if not os.path.exists(candidate):
            continue
        covered = _font_charset(candidate)
        if covered is None:
            # Unreadable: fall back to trusting the path, as before.
            thai_only = thai_only or candidate
            continue
        if ord("ก") not in covered:
            continue
        if ord("A") in covered and ord("0") in covered:
            return candidate
        thai_only = thai_only or candidate
    if thai_only:
        return thai_only
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

# Hook budget. The hook is drawn larger than a subtitle (fontsize 64 vs 60) and
# carries a 24px box border on each side, so fewer clusters fit per line. Set
# below the subtitle budget rather than derived from it, because the failure it
# guards against -- text running off both edges of the frame -- is far worse
# than an extra line break.
_HOOK_CHARS_PER_LINE = 20
_HOOK_MAX_LINES = 2

# Unicode general categories the Thai font has no glyphs for.
_UNRENDERABLE = frozenset({"So", "Sk", "Cf", "Cn", "Co", "Cs"})


@lru_cache(maxsize=4)
def _font_charset(font_path: str) -> frozenset[int] | None:
    """Codepoints `font_path` has glyphs for, or None if it cannot be read."""
    try:
        from fontTools.ttLib import TTFont

        # fontNumber=0 picks the first face of a .ttc collection (Thonburi.ttc
        # is one of the macOS dev fallbacks); lazy avoids parsing outlines.
        font = TTFont(font_path, fontNumber=0, lazy=True)
        try:
            covered: set[int] = set()
            for table in font["cmap"].tables:
                covered.update(table.cmap.keys())
        finally:
            font.close()
        return frozenset(covered) or None
    except Exception:
        return None


def _strip_unrenderable(text: str, font: str | None = None) -> str:
    """Drop characters `font` cannot draw.

    drawtext takes ONE fontfile and has no fallback chain, so any codepoint
    missing from the Thai font renders as a tofu box instead of falling back
    to an emoji font. A shipped tips video had `□□□□□□□` mid-hook where the
    model had written emoji.

    Filtering by the font's actual cmap rather than by Unicode category,
    because guessing categories is whack-a-mole: the first attempt stripped
    So/Sk/Cf and still shipped a tofu box, since `U+FE0F` VARIATION
    SELECTOR-16 is category **Mn** -- the same category as Thai tone marks,
    which must be kept. Removing the emoji while leaving its selector behind
    produced exactly one leftover box. Coverage also catches CJK (Lo) and the
    ideographic space (Zs), which no category rule aimed at emoji would.

    Falls back to the category heuristic when the font cannot be parsed, so
    an unreadable font degrades to the old behaviour instead of either
    crashing or passing everything through.
    """
    covered = _font_charset(font) if font else None
    if covered is not None:
        kept = [ch for ch in text if ord(ch) in covered]
    else:
        kept = [ch for ch in text if unicodedata.category(ch) not in _UNRENDERABLE]
    return re.sub(r"\s{2,}", " ", "".join(kept)).strip()



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
    wraps the text itself, upstream of libass.

    The wrapping itself is delegated to app.video.thai, which segments Thai
    into real words. The greedy cluster counter that used to live here had no
    notion of word boundaries, so it split `กลุ่มคำ` mid-word and stranded the
    repetition mark `ๆ` alone on a third line in a shipped demo.
    """
    if not text:
        return text
    return "\n".join(thai.wrap(text, max_chars))


def _hook_overlay(font: str | None, hook: str, work_dir: str) -> str:
    """Build the drawtext filter fragment for the hook overlay, or "".

    No Thai font found (e.g. local macOS dev without fonts-noto-core, the
    package the render image installs) means "" — the render proceeds
    without a hook overlay rather than failing the whole compose over a
    missing font file.

    The hook MUST be wrapped before it reaches drawtext, which cannot wrap
    text itself. A shipped tips video proves why: a 44-character Thai hook at
    fontsize 64 measures ~1500px against a 1080px frame, so the centring
    expression `(w-text_w)/2` evaluated NEGATIVE and the headline ran off
    both edges with its first characters cut away. Wrapping keeps every line
    inside the frame; max(0,...) is a belt-and-braces clamp so an
    unexpectedly wide line can still never start off-screen.

    The wrapped text goes through `textfile=` rather than `text=` because a
    newline inside a filter-graph string terminates the option — verified:
    `text='a\\nb'` fails with "Either text, a valid file, a timecode or text
    source must be provided". The path must be ABSOLUTE, since ffmpeg
    resolves a relative one against its own cwd, not work_dir.
    """
    if not hook or not font:
        return ""
    safe = _strip_unrenderable(hook, font).replace("'", "").replace(":", " ")
    if not safe:
        return ""
    lines = thai.wrap(safe, _HOOK_CHARS_PER_LINE) or [safe]
    # Cap the height. drawtext paints an opaque box behind the text, so a
    # long hook does not merely look busy -- it blankets the tips card
    # underneath it (a 4-line hook covered the card's number and headline).
    # Two lines is what a hook needs; anything longer is a caption.
    if len(lines) > _HOOK_MAX_LINES:
        lines = lines[:_HOOK_MAX_LINES]
        lines[-1] = lines[-1].rstrip() + "…"
    path = os.path.abspath(os.path.join(work_dir, "hook.txt"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return (
        f",drawtext=fontfile={font}:textfile={path}:fontcolor=white:fontsize=64:"
        f"line_spacing=12:box=1:boxcolor=black@0.55:boxborderw=24:"
        f"x=max(0\\,(w-text_w)/2):y=220:"
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
    segments: list[Segment], hook: str, work_dir: str, subtitles: bool = True,
    music_track: str | None = None, music_lufs: float = -33.0,
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
    # The bed is built here, not by the caller, because `total` is this
    # function's own notion of the finished timeline -- a caller computing
    # it independently would drift the moment clip fitting changes.
    bed = make_bed(music_track, total, work_dir, music_lufs) if music_track else None

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

    hook_frag = _hook_overlay(font, hook, work_dir)
    if hook_frag:
        vf_parts.append(hook_frag.lstrip(","))
    vf = ",".join(vf_parts)

    mp4 = os.path.join(work_dir, "final.mp4")
    cmd = ["ffmpeg", "-y", "-i", video, "-i", voice]
    # Input 0 is the video and input 1 the narration; each extra audio bed
    # (UI blips, music) appends another input, so the amix label list is built
    # from the count rather than hard-coded -- a fixed "[1:a][2:a]" silently
    # drops whichever bed lands at index 3.
    extra = [p for p in (blips, bed) if p]
    if extra:
        for path in extra:
            cmd += ["-i", path]
        n = 1 + len(extra)
        labels = "".join(f"[{i}:a]" for i in range(1, n + 1))
        # normalize=0 keeps amix from rescaling by input count, which is what
        # preserves the deliberate level gap between the -33 LUFS bed and the
        # narration; the trailing loudnorm lifts the whole mix to spec.
        cmd += ["-filter_complex", f"{labels}amix=inputs={n}:normalize=0,loudnorm[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-af", "loudnorm", "-map", "0:v", "-map", "1:a"]
    if vf:
        cmd += ["-vf", vf]
    # -ar is NOT optional here. The loudnorm filter above resamples to 192kHz
    # internally and emits at that rate; the AAC encoder then clamps to its
    # own 96kHz ceiling. Without this the factory ships 96kHz audio built from
    # a 24kHz TTS source -- four times the data for zero added information,
    # off the standard rates social platforms expect. 48kHz is the norm.
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-ar", "48000", "-shortest", mp4]
    run(cmd)

    poster = os.path.join(work_dir, "poster.jpg")
    run(["ffmpeg", "-y", "-i", mp4, "-ss", "1", "-frames:v", "1", poster])
    return mp4, poster
