"""Download the CC0 music beds named in strategy.yaml into the render image.

Run at image-BUILD time (see render/Dockerfile), never at render time. Baking
the tracks in means a render never depends on a third-party host being
reachable, and keeps ~3MB binaries out of git.

Fails the build on any problem -- a missing or renamed track must surface as
a red build, not as an image that quietly renders every video without music.

Usage: python render/fetch_music.py <strategy.yaml> <out-dir>
"""

import os
import ssl
import sys
import urllib.error
import urllib.request

import yaml


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS context that also works outside the render image.

    The image's Linux python trusts the system CA store, so the plain
    default context is enough there. A macOS python installed outside the
    system (the usual local dev case) ships no CA bundle and fails every
    HTTPS fetch with CERTIFICATE_VERIFY_FAILED, which makes this script
    impossible to test before pushing a build. certifi comes in via the
    project's own dependencies, so prefer it when present -- and keep
    verification ON either way rather than reaching for the unverified
    context that this error usually tempts people into.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

# AIVDO serves its FreePD library publicly and unauthenticated: the catalogue
# at /api/music/tracks and the files themselves under /static/music. Verified
# 2026-08-08 (200, audio/mpeg, no key). If this ever starts requiring auth,
# the build breaks here rather than in production.
BASE = os.environ.get("MUSIC_BASE_URL", "https://aivdo-api-b7iz53omoq-as.a.run.app")
TIMEOUT = 60


def wanted_tracks(strategy_path: str) -> list[str]:
    with open(strategy_path, encoding="utf-8") as f:
        music = (yaml.safe_load(f) or {}).get("music") or {}
    ids: list[str] = []
    for fmt in ("tips", "demo"):
        for track in music.get(fmt) or []:
            if track not in ids:
                ids.append(track)
    return ids


def fetch(track: str, out_dir: str) -> str:
    url = f"{BASE}/static/music/{track}.mp3"
    dest = os.path.join(out_dir, f"{track}.mp3")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=_ssl_context()) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise SystemExit(f"fetch_music: {track} <- {url} failed: {exc}") from exc
    # A 404 page or an auth redirect would still "download"; a real mp3 is
    # never this small, so treat a tiny body as a failed fetch rather than
    # writing an unplayable file that only fails later inside ffmpeg.
    if len(data) < 50_000:
        raise SystemExit(f"fetch_music: {track} returned only {len(data)} bytes from {url}")
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def main() -> None:
    strategy_path, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    tracks = wanted_tracks(strategy_path)
    if not tracks:
        print("fetch_music: strategy.yaml names no music tracks; nothing to do")
        return
    for track in tracks:
        dest = fetch(track, out_dir)
        print(f"fetch_music: {track} -> {dest} ({os.path.getsize(dest)} bytes)")


if __name__ == "__main__":
    main()
