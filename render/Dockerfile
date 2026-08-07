# Build from the REPO ROOT, like backend/Dockerfile — strategy.yaml and
# scenarios/ both live one level above render/:
#
#   docker build -f render/Dockerfile -t automarketing-render .
#
# Base image pinned to Playwright 1.62.0 (NOT the v1.49.0 some older docs
# reference) to match `playwright>=1.62,<2` in backend/pyproject.toml — the
# mcr.microsoft.com/playwright/python images ship browser binaries baked in
# at the exact version in the tag, so a mismatched tag would leave the
# installed playwright Python package looking for a Chromium revision that
# was never downloaded into the image.
#
# Distro suffix is `-noble` (Ubuntu 24.04), NOT `-jammy` (22.04) — verified
# by pulling both remotely: `-jammy`'s system python3 is 3.10.12, which
# fails `backend/pyproject.toml`'s `requires-python = ">=3.12"` outright
# during `pip install .` below. `-noble` ships Python 3.12.3 with the same
# Playwright 1.62.0 / Chromium pairing, and the same
# `NotoSansThai-Regular.ttf` at the same `/usr/share/fonts/truetype/noto/`
# path that `backend/app/video/compose.py`'s FONT constant expects
# (confirmed on both tags before choosing this one).
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

COPY backend/app ./app
COPY scenarios ./scenarios
COPY strategy.yaml ./strategy.yaml
ENV STRATEGY_PATH=./strategy.yaml SCENARIO_ROOT=./scenarios PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.video.worker"]
