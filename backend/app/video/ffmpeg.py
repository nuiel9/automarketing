import subprocess


class FFmpegError(Exception):
    pass


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise FFmpegError(" | ".join(tail) or f"{cmd[0]} exited {proc.returncode}")


def probe_duration(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}")
    return float(proc.stdout.strip())


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_from_segments(segments: list[tuple[str, float]]) -> str:
    lines, clock = [], 0.0
    for i, (text, seconds) in enumerate(segments, start=1):
        start, end = clock, clock + seconds
        lines.append(f"{i}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
        clock = end
    return "\n".join(lines)


def fit_filter(clip_seconds: float, target_seconds: float, mode: str) -> str:
    """Video filter that makes a clip exactly target_seconds long.

    A clip shorter than its narration always holds its last frame — speeding
    *up* a short clip would make the product look frantic and desynced.
    """
    if clip_seconds <= target_seconds:
        pad = round(target_seconds - clip_seconds, 3)
        return f"tpad=stop_duration={pad}:stop_mode=clone"
    if mode == "tail":
        start = round(clip_seconds - target_seconds, 3)
        return f"trim=start={start},setpts=PTS-STARTPTS"
    if mode == "hold":
        return f"trim=duration={target_seconds},setpts=PTS-STARTPTS"
    ratio = round(target_seconds / clip_seconds, 3)
    return f"setpts={ratio}*PTS"


def blip_command(kind: str, path: str) -> list[str]:
    """Synthesize a UI sound — no third-party audio ships in this repo."""
    freq, dur = (1200, 0.05) if kind == "click" else (2400, 0.02)
    return [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={dur}:sample_rate=24000",
        "-af", "afade=t=out:st=0:d=%s,volume=0.25" % dur,
        "-ac", "1", path,
    ]
