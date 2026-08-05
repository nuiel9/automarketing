# Video Factory (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the marketing videos themselves — Playwright drives production eduverse.one and screen-records it, Kavee narrates in Thai, and a 1080×1920 MP4 lands in the existing review queue.

**Architecture:** A separate render image (Chromium + ffmpeg + Thai fonts) runs as a Cloud Run **Job**. The API moves an item to `rendering` and dispatches the job; the job reads the item from Postgres over the VPC, renders, uploads the MP4 + poster through the existing `MediaStore`, and writes the item back to `in_review`. No callback endpoint, no polling. Every step's Thai narration lives in the scenario file, and each recorded clip is cut to its own narration duration — so audio and video cannot drift.

**Tech Stack:** Python 3.12, Playwright (Chromium), ffmpeg/ffprobe, google-genai (`gemini-3.1-flash-tts-preview`, voice `Charon`), PyYAML + pydantic, google-cloud-run, SQLAlchemy/Alembic, Next.js frontend.

## Global Constraints

- Python ≥ 3.12. All new backend code lives under `backend/app/video/` except the API route and dispatcher wiring.
- TTS: model exactly `gemini-3.1-flash-tts-preview`, voice exactly `Charon` (matches eduverse-one's Kavee so the marketing voice IS the product voice).
- Tips content generation: model `gemini-3.6-flash` via `client.models.generate_content` with `response_schema` (same pattern as `app/captions.py`); never parse free-text JSON.
- Output contract, identical for every renderer: 1080×1920 H.264 `yuv420p` MP4 + a JPEG poster frame, both stored via the existing `app.media.get_store(settings)`.
- **No third-party audio files in the repo.** UI sounds are synthesized with ffmpeg at render time.
- Statuses (item): `idea|planned|rendering|in_review|approved|scheduled|posted|rejected|failed`. Phase 2 adds the transitions `idea → rendering` and `failed → rendering`.
- `format` values: `founder_clip` (existing), `demo`, `tips`.
- Secrets only via env: `GEMINI_API_KEY` (exists), `DEMO_EMAIL`, `DEMO_PASSWORD` (new). Never committed.
- No network calls in unit tests: TTS, Playwright, Cloud Run and Gemini are all mocked or replaced by fixtures. The one end-to-end render test uses a **local fixture HTML page**, never production.
- Commit after every green test cycle, conventional prefixes (`feat:`, `test:`, `chore:`, `docs:`).
- Existing helpers to reuse, not reinvent: `app.media.get_store`, `app.state.transition`, `app.notify.line_notify`, `app.config.get_settings`, `app.api.auth.require_admin`, `app.models.ContentItem`.

---

### Task 1: Config, schema migration, state transitions

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/state.py`
- Create: `backend/alembic/versions/0002_video_factory.py`
- Test: `backend/tests/test_state.py` (extend), `backend/tests/test_models.py` (extend)

**Interfaces:**
- Consumes: `Settings` (Task 0 of Phase 1), `ContentItem`, `ITEM_TRANSITIONS`.
- Produces: `Settings.render_job_name`, `.render_job_region`, `.gcp_project`, `.demo_email`, `.demo_password`, `.tts_model`, `.kavee_voice`, `.tips_model`, `.render_dispatcher`; `ContentItem.scenario`, `ContentItem.render_error`; transitions `idea → rendering`, `failed → rendering`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_state.py`:

```python
@pytest.mark.parametrize("src,dst", [("idea", "rendering"), ("failed", "rendering")])
def test_render_transitions_allowed(src, dst):
    item = make(src)
    transition(item, dst)
    assert item.status == dst
```

Append to `backend/tests/test_models.py`:

```python
def test_item_carries_scenario_and_render_error(db):
    item = ContentItem(
        slug="w32-demo-tgat", topic="t", status="idea",
        format="demo", scenario="tgat-demo", render_error=None,
    )
    db.add(item)
    db.commit()
    loaded = db.get(ContentItem, item.id)
    assert loaded.format == "demo"
    assert loaded.scenario == "tgat-demo"
    assert loaded.render_error is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_state.py tests/test_models.py -v`
Expected: FAIL — `InvalidTransition` for the new transitions, `TypeError: 'scenario' is an invalid keyword argument`.

- [ ] **Step 3: Implement**

In `backend/app/state.py`, change two entries (leave the rest untouched):

```python
    "idea": {"in_review", "rendering"},
    "failed": {"scheduled", "rendering"},
```

In `backend/app/models.py`, add to `ContentItem` after `media_token`:

```python
    scenario: Mapped[str | None] = mapped_column(String(80), nullable=True)
    render_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

In `backend/app/config.py`, add to `Settings` after `gemini_model`:

```python
    tips_model: str = "gemini-3.6-flash"
    tts_model: str = "gemini-3.1-flash-tts-preview"
    kavee_voice: str = "Charon"

    render_dispatcher: str = "cloudrun"     # "cloudrun" | "local"
    gcp_project: str = ""
    render_job_name: str = "automarketing-render"
    render_job_region: str = "asia-southeast1"

    demo_email: str = ""
    demo_password: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS (all existing tests plus the two new ones).

- [ ] **Step 5: Write the migration**

`backend/alembic/versions/0002_video_factory.py`:

```python
"""video factory: scenario + render_error

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_items", sa.Column("scenario", sa.String(length=80), nullable=True))
    op.add_column("content_items", sa.Column("render_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("content_items", "render_error")
    op.drop_column("content_items", "scenario")
```

Verify it matches the models: `cd backend && DATABASE_URL=sqlite:///./_check.db .venv/bin/alembic upgrade head && rm -f _check.db`
Expected: runs clean, no error.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: video factory schema, config and render state transitions"
```

---

### Task 2: Scenario loader

**Files:**
- Create: `backend/app/video/__init__.py` (empty), `backend/app/video/scenario.py`
- Create: `scenarios/fixture-demo.yaml`
- Test: `backend/tests/test_scenario.py`

**Interfaces:**
- Produces: `app.video.scenario.Step` (pydantic: `narration: str`, `action: Literal["goto","type","click","wait_for","wait_ms","scroll"]`, `url: str|None`, `selector: str|None`, `text: str|None`, `ms: int|None`, `sound: Literal["keystroke","click"]|None`, `fit: Literal["speedup","tail","hold"] = "speedup"`, `timeout_ms: int = 30000`), `Scenario` (`name: str`, `login: bool = True`, `steps: list[Step]`), `load_scenario(name: str, root: str) -> Scenario`, `ScenarioError`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_scenario.py`:

```python
import pytest

from app.video.scenario import ScenarioError, load_scenario

GOOD = """
name: fixture-demo
login: false
steps:
  - narration: "พิมพ์เป้าหมาย"
    action: type
    selector: "#goal"
    text: "ติว TGAT"
    sound: keystroke
  - narration: "รอระบบสร้างคอร์ส"
    action: wait_for
    selector: "#done"
    fit: speedup
"""


def test_load_valid_scenario(tmp_path):
    (tmp_path / "fixture-demo.yaml").write_text(GOOD, encoding="utf-8")
    s = load_scenario("fixture-demo", str(tmp_path))
    assert s.name == "fixture-demo"
    assert s.login is False
    assert len(s.steps) == 2
    assert s.steps[0].sound == "keystroke"
    assert s.steps[1].fit == "speedup"
    assert s.steps[0].fit == "speedup"       # default applied


def test_missing_file_raises(tmp_path):
    with pytest.raises(ScenarioError):
        load_scenario("nope", str(tmp_path))


def test_type_step_without_selector_raises(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        'name: bad\nsteps:\n  - narration: "x"\n    action: type\n    text: "hi"\n',
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError):
        load_scenario("bad", str(tmp_path))


def test_goto_step_without_url_raises(tmp_path):
    (tmp_path / "bad2.yaml").write_text(
        'name: bad2\nsteps:\n  - narration: "x"\n    action: goto\n', encoding="utf-8"
    )
    with pytest.raises(ScenarioError):
        load_scenario("bad2", str(tmp_path))


def test_empty_narration_raises(tmp_path):
    (tmp_path / "bad3.yaml").write_text(
        'name: bad3\nsteps:\n  - narration: ""\n    action: wait_ms\n    ms: 100\n',
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError):
        load_scenario("bad3", str(tmp_path))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_scenario.py -v`
Expected: FAIL — `ModuleNotFoundError: app.video.scenario`.

- [ ] **Step 3: Implement**

`backend/app/video/scenario.py`:

```python
import os
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError, model_validator


class ScenarioError(Exception):
    pass


class Step(BaseModel):
    narration: str
    action: Literal["goto", "type", "click", "wait_for", "wait_ms", "scroll"]
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    ms: int | None = None
    sound: Literal["keystroke", "click"] | None = None
    fit: Literal["speedup", "tail", "hold"] = "speedup"
    timeout_ms: int = 30_000

    @model_validator(mode="after")
    def _check_required_fields(self) -> "Step":
        if not self.narration.strip():
            raise ValueError("narration must not be empty")
        needs_selector = {"type", "click", "wait_for", "scroll"}
        if self.action in needs_selector and not self.selector:
            raise ValueError(f"action {self.action} requires a selector")
        if self.action == "goto" and not self.url:
            raise ValueError("action goto requires a url")
        if self.action == "type" and self.text is None:
            raise ValueError("action type requires text")
        if self.action == "wait_ms" and self.ms is None:
            raise ValueError("action wait_ms requires ms")
        return self


class Scenario(BaseModel):
    name: str
    login: bool = True
    steps: list[Step]

    @model_validator(mode="after")
    def _check_steps(self) -> "Scenario":
        if not self.steps:
            raise ValueError("scenario needs at least one step")
        return self


def load_scenario(name: str, root: str) -> Scenario:
    path = os.path.join(root, f"{os.path.basename(name)}.yaml")
    if not os.path.exists(path):
        raise ScenarioError(f"scenario not found: {name}")
    try:
        with open(path, encoding="utf-8") as f:
            return Scenario.model_validate(yaml.safe_load(f))
    except (ValidationError, yaml.YAMLError) as exc:
        raise ScenarioError(f"invalid scenario {name}: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_scenario.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Add the fixture scenario used by the e2e test in Task 8**

`scenarios/fixture-demo.yaml`:

```yaml
name: fixture-demo
login: false
steps:
  - narration: "พิมพ์เป้าหมายที่อยากเรียน"
    action: type
    selector: "#goal"
    text: "ติว TGAT"
    sound: keystroke
  - narration: "ระบบสร้างคอร์สให้ทันที"
    action: click
    selector: "#go"
    sound: click
  - narration: "แล้วคุยกับพี่กวีได้เลย"
    action: wait_for
    selector: "#done"
    fit: speedup
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: scenario yaml loader with per-step narration"
```

---

### Task 3: KaveeVoice (Gemini TTS)

**Files:**
- Create: `backend/app/video/tts.py`
- Test: `backend/tests/test_tts.py`

**Interfaces:**
- Consumes: `get_settings()` (`tts_model`, `kavee_voice`, `gemini_api_key`).
- Produces: `app.video.tts.Narration` (dataclass: `text: str`, `path: str`, `seconds: float`), `app.video.tts.synthesize(text: str, out_dir: str) -> Narration`, `app.video.tts.TTSError`. Writes a 24 kHz mono WAV. Identical text in the same `out_dir` reuses the existing file (hash-named) without calling the API.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tts.py`:

```python
import os
import struct
import wave

import pytest

import app.video.tts as tts
from app.video.tts import TTSError, synthesize


def _pcm(seconds: float = 0.5, rate: int = 24_000) -> bytes:
    return struct.pack("<h", 0) * int(rate * seconds)


class FakePart:
    def __init__(self, data): self.inline_data = type("D", (), {"data": data})()


class FakeModels:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls = data, fail, 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("tts down")
        self.kwargs = kwargs
        cand = type("C", (), {"content": type("X", (), {"parts": [FakePart(self.data)]})()})()
        return type("R", (), {"candidates": [cand]})()


class FakeClient:
    def __init__(self, data=None, fail=False): self.models = FakeModels(data, fail)


def test_synthesize_writes_wav_and_measures_duration(tmp_path, monkeypatch):
    fake = FakeClient(_pcm(0.5))
    monkeypatch.setattr(tts, "_client", lambda: fake)
    n = synthesize("สวัสดีครับ", str(tmp_path))
    assert os.path.exists(n.path)
    assert 0.45 < n.seconds < 0.55
    with wave.open(n.path) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 24_000
    assert fake.models.kwargs["model"] == "gemini-3.1-flash-tts-preview"


def test_synthesize_is_cached_by_text(tmp_path, monkeypatch):
    fake = FakeClient(_pcm(0.3))
    monkeypatch.setattr(tts, "_client", lambda: fake)
    a = synthesize("ซ้ำ", str(tmp_path))
    b = synthesize("ซ้ำ", str(tmp_path))
    assert a.path == b.path
    assert fake.models.calls == 1          # second call served from disk


def test_api_failure_raises_tts_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "_client", lambda: FakeClient(fail=True))
    with pytest.raises(TTSError):
        synthesize("x", str(tmp_path))


def test_empty_audio_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "_client", lambda: FakeClient(b""))
    with pytest.raises(TTSError):
        synthesize("x", str(tmp_path))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_tts.py -v`
Expected: FAIL — `ModuleNotFoundError: app.video.tts`.

- [ ] **Step 3: Implement**

`backend/app/video/tts.py`:

```python
import hashlib
import os
import wave
from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings

SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2


class TTSError(Exception):
    pass


@dataclass
class Narration:
    text: str
    path: str
    seconds: float


@lru_cache
def _client():
    # Cached: a per-call temporary Client can be GC'd mid-request, closing the
    # transport under the in-flight call (same trap fixed in app/captions.py).
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=get_settings().gemini_api_key,
        http_options=types.HttpOptions(timeout=120_000),
    )


def _write_wav(path: str, pcm: bytes) -> float:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)


def synthesize(text: str, out_dir: str) -> Narration:
    os.makedirs(out_dir, exist_ok=True)
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(out_dir, f"{key}.wav")
    if os.path.exists(path):
        with wave.open(path) as w:
            return Narration(text, path, w.getnframes() / w.getframerate())

    settings = get_settings()
    from google.genai import types

    try:
        resp = _client().models.generate_content(
            model=settings.tts_model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=settings.kavee_voice
                        )
                    )
                ),
            ),
        )
        pcm = resp.candidates[0].content.parts[0].inline_data.data
    except Exception as exc:
        raise TTSError(str(exc)) from exc

    if not pcm:
        raise TTSError("tts returned no audio")
    return Narration(text, path, _write_wav(path, pcm))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_tts.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Kavee TTS (gemini tts, voice Charon) with on-disk cache"
```

---

### Task 4: Composer — ffmpeg helpers

**Files:**
- Create: `backend/app/video/ffmpeg.py`
- Test: `backend/tests/test_ffmpeg.py`

**Interfaces:**
- Produces: `app.video.ffmpeg.probe_duration(path) -> float`; `srt_from_segments(list[tuple[str, float]]) -> str`; `fit_filter(clip_seconds, target_seconds, mode) -> str`; `blip_command(kind, path) -> list[str]`; `run(cmd: list[str]) -> None` (raises `FFmpegError` with the stderr tail); `FFmpegError`.
- Note: `fit_filter` returns only the `-filter:v` value so it is unit-testable without running ffmpeg.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_ffmpeg.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_ffmpeg.py -v`
Expected: FAIL — `ModuleNotFoundError: app.video.ffmpeg`.

- [ ] **Step 3: Implement**

`backend/app/video/ffmpeg.py`:

```python
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
        return f"tpad=stop_mode=clone:stop_duration={pad}"
    if mode == "tail":
        start = round(clip_seconds - target_seconds, 3)
        return f"trim=start={start},setpts=PTS-STARTPTS"
    if mode == "hold":
        return f"trim=duration={target_seconds},setpts=PTS-STARTPTS"
    ratio = round(target_seconds / clip_seconds, 4)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_ffmpeg.py -v`
Expected: PASS (7 tests). `test_run_raises_with_stderr_tail` needs ffmpeg installed; if it is missing locally, install it (`brew install ffmpeg`) — the render image has it.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: ffmpeg helpers — srt, fit filters, synthesized ui blips"
```

---

### Task 5: Composer — assemble the final MP4

**Files:**
- Create: `backend/app/video/compose.py`
- Test: `backend/tests/test_compose.py`

**Interfaces:**
- Consumes: `app.video.ffmpeg` (all of it), `app.video.tts.Narration`.
- Produces: `app.video.compose.Segment` (dataclass: `clip_path: str`, `narration: Narration`, `fit: str`, `sound: str | None`), `app.video.compose.compose(segments: list[Segment], hook: str, work_dir: str) -> tuple[str, str]` returning `(mp4_path, poster_path)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_compose.py`:

```python
import os
import subprocess

import pytest

from app.video.compose import Segment, compose
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
```

Register the marker in `backend/pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = ["slow: renders real media with ffmpeg"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_compose.py -v`
Expected: FAIL — `ModuleNotFoundError: app.video.compose`.

- [ ] **Step 3: Implement**

`backend/app/video/compose.py`:

```python
import os
from dataclasses import dataclass

from app.video.ffmpeg import blip_command, fit_filter, probe_duration, run, srt_from_segments
from app.video.tts import Narration

WIDTH, HEIGHT = 1080, 1920
FONT = "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"
HOOK_SECONDS = 3


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
    if hook:
        safe = hook.replace("'", "").replace(":", " ")
        vf += (
            f",drawtext=fontfile={FONT}:text='{safe}':fontcolor=white:fontsize=64:"
            f"box=1:boxcolor=black@0.55:boxborderw=24:x=(w-text_w)/2:y=220:"
            f"enable='lt(t,{HOOK_SECONDS})'"
        )

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_compose.py -v`
Expected: PASS. If the Thai font path does not exist locally, the `drawtext` hook is the only part that needs it — install `fonts-noto` locally or run this test in the render image (Task 9). The test passes `hook="ทดสอบ"`, so make the font available or temporarily verify with `hook=""` and re-run with the font present before committing.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: composer — fit clips to narration, burn subs, hook overlay, loudnorm"
```

---

### Task 6: DemoRenderer (Playwright)

**Files:**
- Create: `backend/app/video/demo.py`
- Test: `backend/tests/test_demo_renderer.py`

**Interfaces:**
- Consumes: `Scenario`/`Step` (Task 2), `synthesize` (Task 3), `Segment` (Task 5).
- Produces: `app.video.demo.render_demo(scenario: Scenario, work_dir: str, base_url: str, login: tuple[str, str] | None) -> list[Segment]`, `app.video.demo.RenderStepError` (carries `.step_index`, `.screenshot_path`).
- Playwright is imported inside the function so unit tests import the module without the browser installed.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_demo_renderer.py` — drives the real Playwright API against a **local file**, never production:

```python
import os

import pytest

from app.video.demo import RenderStepError, render_demo
from app.video.scenario import Scenario, Step
from app.video.tts import Narration

FIXTURE_HTML = """<!doctype html><meta charset=utf-8>
<body style="background:#111;color:#fff;font-size:48px">
<input id=goal><button id=go onclick="setTimeout(()=>{document.body.insertAdjacentHTML('beforeend','<div id=done>เสร็จแล้ว</div>')},300)">go</button>
</body>"""


@pytest.fixture
def fixture_url(tmp_path):
    p = tmp_path / "fixture.html"
    p.write_text(FIXTURE_HTML, encoding="utf-8")
    return f"file://{p}"


def _fake_synth(tmp_path):
    import subprocess

    def _synth(text, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{abs(hash(text))}.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "sine=frequency=300:duration=1:sample_rate=24000", "-ac", "1", path],
            capture_output=True, check=True,
        )
        return Narration(text=text, path=path, seconds=1.0)

    return _synth


@pytest.mark.slow
def test_render_demo_returns_one_segment_per_step(tmp_path, fixture_url, monkeypatch):
    import app.video.demo as demo

    monkeypatch.setattr(demo, "synthesize", _fake_synth(tmp_path))
    scenario = Scenario(name="fx", login=False, steps=[
        Step(narration="พิมพ์", action="type", selector="#goal", text="hi", sound="keystroke"),
        Step(narration="กด", action="click", selector="#go", sound="click"),
        Step(narration="เสร็จ", action="wait_for", selector="#done"),
    ])
    segments = render_demo(scenario, str(tmp_path), base_url=fixture_url, login=None)

    assert len(segments) == 3
    for seg in segments:
        assert os.path.exists(seg.clip_path)
        assert seg.narration.seconds == 1.0
    assert segments[0].sound == "keystroke"


@pytest.mark.slow
def test_missing_selector_raises_with_screenshot(tmp_path, fixture_url, monkeypatch):
    import app.video.demo as demo

    monkeypatch.setattr(demo, "synthesize", _fake_synth(tmp_path))
    scenario = Scenario(name="fx", login=False, steps=[
        Step(narration="ไม่มีปุ่มนี้", action="click", selector="#missing", timeout_ms=1500),
    ])
    with pytest.raises(RenderStepError) as exc:
        render_demo(scenario, str(tmp_path), base_url=fixture_url, login=None)
    assert exc.value.step_index == 0
    assert os.path.exists(exc.value.screenshot_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_demo_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: app.video.demo`.
(Install browsers first if needed: `.venv/bin/pip install playwright && .venv/bin/playwright install chromium`.)

- [ ] **Step 3: Implement**

`backend/app/video/demo.py`:

```python
import os
import time

from app.video.compose import Segment
from app.video.ffmpeg import run
from app.video.scenario import Scenario, Step
from app.video.tts import synthesize

VIEWPORT = {"width": 540, "height": 960}   # 2x-scaled to 1080x1920 by the composer


class RenderStepError(Exception):
    def __init__(self, message: str, step_index: int, screenshot_path: str):
        super().__init__(message)
        self.step_index = step_index
        self.screenshot_path = screenshot_path


def _do_step(page, step: Step, base_url: str) -> None:
    if step.action == "goto":
        page.goto(step.url or base_url, timeout=step.timeout_ms)
    elif step.action == "type":
        page.fill(step.selector, "", timeout=step.timeout_ms)
        page.type(step.selector, step.text or "", delay=60)
    elif step.action == "click":
        page.click(step.selector, timeout=step.timeout_ms)
    elif step.action == "wait_for":
        page.wait_for_selector(step.selector, timeout=step.timeout_ms)
    elif step.action == "wait_ms":
        page.wait_for_timeout(step.ms or 0)
    elif step.action == "scroll":
        page.locator(step.selector).scroll_into_view_if_needed(timeout=step.timeout_ms)


def render_demo(
    scenario: Scenario, work_dir: str, base_url: str, login: tuple[str, str] | None
) -> list[Segment]:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    os.makedirs(work_dir, exist_ok=True)
    audio_dir = os.path.join(work_dir, "audio")
    narrations = [synthesize(s.narration, audio_dir) for s in scenario.steps]

    video_dir = os.path.join(work_dir, "session")
    marks: list[tuple[float, float]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(
            viewport=VIEWPORT, device_scale_factor=2,
            record_video_dir=video_dir, record_video_size=VIEWPORT,
            locale="th-TH",
        )
        page = context.new_page()
        page.goto(base_url, timeout=60_000)

        if scenario.login and login:
            email, password = login
            page.fill("[data-testid=email]", email, timeout=30_000)
            page.fill("[data-testid=password]", password)
            page.click("[data-testid=login-submit]")
            page.wait_for_load_state("networkidle", timeout=60_000)

        t0 = time.monotonic()
        for index, step in enumerate(scenario.steps):
            start = time.monotonic() - t0
            try:
                _do_step(page, step, base_url)
            except PlaywrightError as exc:
                shot = os.path.join(work_dir, f"fail_step_{index}.png")
                page.screenshot(path=shot)
                context.close(); browser.close()
                raise RenderStepError(
                    f"step {index} ({step.action} {step.selector or step.url}): {exc}",
                    index, shot,
                ) from exc
            marks.append((start, time.monotonic() - t0))

        session_video = page.video.path()
        context.close()
        browser.close()

    segments = []
    for index, (step, narration) in enumerate(zip(scenario.steps, narrations)):
        start, end = marks[index]
        clip = os.path.join(work_dir, f"step_{index}.mp4")
        run(["ffmpeg", "-y", "-i", session_video, "-ss", f"{start:.3f}",
             "-to", f"{max(end, start + 0.4):.3f}", "-an", "-pix_fmt", "yuv420p", clip])
        segments.append(Segment(clip, narration, fit=step.fit, sound=step.sound))
    return segments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_demo_renderer.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: demo renderer — playwright session recording cut per narrated step"
```

---

### Task 7: TipsRenderer

**Files:**
- Create: `backend/app/video/tips.py`
- Test: `backend/tests/test_tips_renderer.py`

**Interfaces:**
- Consumes: `synthesize` (Task 3), `Segment` (Task 5), `Strategy` (`app.strategy`).
- Produces: `app.video.tips.TipCard` (pydantic: `headline: str`, `body: str`), `TipSet` (`hook: str`, `cards: list[TipCard]`), `write_tips(topic: str, strategy: Strategy, n: int = 5) -> TipSet`, `render_tips(tips: TipSet, work_dir: str) -> list[Segment]`, `TipsError`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tips_renderer.py`:

```python
import os

import pytest

import app.video.tips as tips_mod
from app.strategy import Strategy
from app.video.tips import TipCard, TipSet, TipsError, render_tips, write_tips
from app.video.tts import Narration

STRATEGY = Strategy(voice="v", audiences=["a"], banned_words=[], platform_notes={})
FAKE = TipSet(hook="5 ข้อสอบที่คนพลาด", cards=[
    TipCard(headline="ข้อ 1", body="อ่านโจทย์ให้ครบ"),
    TipCard(headline="ข้อ 2", body="จับเวลาเสมอ"),
])


class FakeModels:
    def __init__(self, text=None, fail=False):
        self.text, self.fail, self.kwargs = text, fail, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise RuntimeError("down")
        return type("R", (), {"text": self.text})()


class FakeClient:
    def __init__(self, text=None, fail=False): self.models = FakeModels(text, fail)


def test_write_tips_uses_structured_output(monkeypatch):
    fake = FakeClient(FAKE.model_dump_json())
    monkeypatch.setattr(tips_mod, "_genai_client", lambda: fake)
    out = write_tips("TGAT", STRATEGY, n=2)
    assert out.hook == "5 ข้อสอบที่คนพลาด"
    assert len(out.cards) == 2
    assert fake.models.kwargs["config"].response_schema is TipSet


def test_write_tips_wraps_errors(monkeypatch):
    monkeypatch.setattr(tips_mod, "_genai_client", lambda: FakeClient(fail=True))
    with pytest.raises(TipsError):
        write_tips("x", STRATEGY)


@pytest.mark.slow
def test_render_tips_produces_one_segment_per_card(tmp_path, monkeypatch):
    import subprocess

    def _synth(text, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        p = os.path.join(out_dir, f"{abs(hash(text))}.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                        "-i", "sine=frequency=300:duration=1:sample_rate=24000",
                        "-ac", "1", p], capture_output=True, check=True)
        return Narration(text, p, 1.0)

    monkeypatch.setattr(tips_mod, "synthesize", _synth)
    segments = render_tips(FAKE, str(tmp_path))
    assert len(segments) == 2
    for seg in segments:
        assert os.path.exists(seg.clip_path)
        assert seg.fit == "hold"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_tips_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: app.video.tips`.

- [ ] **Step 3: Implement**

`backend/app/video/tips.py`:

```python
import os
from functools import lru_cache

from pydantic import BaseModel

from app.config import get_settings
from app.strategy import Strategy
from app.video.compose import Segment
from app.video.ffmpeg import run
from app.video.tts import synthesize

CARD_W, CARD_H = 540, 960


class TipsError(Exception):
    pass


class TipCard(BaseModel):
    headline: str
    body: str


class TipSet(BaseModel):
    hook: str
    cards: list[TipCard]


@lru_cache
def _genai_client():
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=get_settings().gemini_api_key,
        http_options=types.HttpOptions(timeout=120_000),
    )


def write_tips(topic: str, strategy: Strategy, n: int = 5) -> TipSet:
    from google.genai import types

    system = (
        "You write short Thai tips-card content for Eduverse One, an AI tutor app.\n"
        f"Brand voice: {strategy.voice}\n"
        f"Audiences: {', '.join(strategy.audiences)}\n"
        f"Write exactly {n} cards. Each headline is at most 6 Thai words; each body is "
        "one sentence a student can act on. Plus one hook line for the video opening. "
        "No URLs, no invented statistics, no guarantees."
    )
    try:
        resp = _genai_client().models.generate_content(
            model=get_settings().tips_model,
            contents=f"หัวข้อ: {topic}",
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=TipSet,
                max_output_tokens=4096,
            ),
        )
    except Exception as exc:
        raise TipsError(str(exc)) from exc
    if not resp.text:
        raise TipsError("tips model returned no output")
    try:
        return TipSet.model_validate_json(resp.text)
    except Exception as exc:
        raise TipsError(f"invalid tips payload: {exc}") from exc


_CARD_HTML = """<!doctype html><meta charset="utf-8">
<style>
 body{{margin:0;width:{w}px;height:{h}px;background:#0F172A;color:#F8FAFC;
   font-family:'Noto Sans Thai',sans-serif;display:flex;flex-direction:column;
   justify-content:center;padding:64px;box-sizing:border-box}}
 .n{{font-size:28px;color:#F59E0B;letter-spacing:4px;margin-bottom:24px}}
 h1{{font-size:64px;line-height:1.2;margin:0 0 32px}}
 p{{font-size:40px;line-height:1.5;margin:0;color:#CBD5E1}}
</style>
<div class="n">{index}</div><h1>{headline}</h1><p>{body}</p>"""


def _card_png(card: TipCard, index: int, path: str) -> None:
    from playwright.sync_api import sync_playwright

    html = _CARD_HTML.format(
        w=CARD_W, h=CARD_H, index=f"{index:02d}",
        headline=card.headline, body=card.body,
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_context(
            viewport={"width": CARD_W, "height": CARD_H}, device_scale_factor=2
        ).new_page()
        page.set_content(html)
        page.screenshot(path=path)
        browser.close()


def render_tips(tips: TipSet, work_dir: str) -> list[Segment]:
    os.makedirs(work_dir, exist_ok=True)
    audio_dir = os.path.join(work_dir, "audio")
    segments = []
    for index, card in enumerate(tips.cards, start=1):
        narration = synthesize(f"{card.headline} {card.body}", audio_dir)
        png = os.path.join(work_dir, f"card_{index}.png")
        _card_png(card, index, png)
        clip = os.path.join(work_dir, f"card_{index}.mp4")
        # slow Ken Burns push so a static card still feels alive
        run(["ffmpeg", "-y", "-loop", "1", "-i", png, "-t", f"{narration.seconds}",
             "-vf", f"scale=2160:3840,zoompan=z='min(zoom+0.0006,1.10)':"
                    f"d={int(narration.seconds * 30)}:s=1080x1920:fps=30",
             "-pix_fmt", "yuv420p", clip])
        segments.append(Segment(clip, narration, fit="hold", sound=None))
    return segments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_tips_renderer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: tips renderer — gemini-written Thai cards with ken burns motion"
```

---

### Task 8: Render worker entrypoint

**Files:**
- Create: `backend/app/video/worker.py`
- Test: `backend/tests/test_render_worker.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7, plus `app.db.SessionLocal`, `app.media.get_store`, `app.state.transition`, `app.notify.line_notify`.
- Produces: `app.video.worker.render_item(session, item_id: str, notify) -> None` — the whole job body, callable in-process (so `LocalDispatcher` and tests use the same path production does), and `python -m app.video.worker` reading `ITEM_ID` from the environment.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_render_worker.py`:

```python
import pytest

import app.video.worker as worker
from app.models import ContentItem
from app.video.compose import Segment
from app.video.demo import RenderStepError
from app.video.tts import Narration


def _item(db, **kw):
    item = ContentItem(slug="w32-demo-x", topic="หัวข้อ", status="rendering",
                       format="demo", scenario="fixture-demo", **kw)
    db.add(item); db.commit()
    return item


def test_successful_render_stores_media_and_moves_to_review(db, tmp_path, monkeypatch):
    item = _item(db)
    seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
    monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))
    monkeypatch.setattr(worker, "compose",
                        lambda segs, hook, work_dir: (str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")))
    for name in ("f.mp4", "p.jpg"):
        (tmp_path / name).write_bytes(b"x")
    saved = {}
    monkeypatch.setattr(worker, "get_store", lambda s: type("S", (), {
        "save": lambda self, data, filename: saved.setdefault(filename, "stored/" + filename)
    })())

    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "in_review"
    assert item.media_path.startswith("stored/")
    assert item.render_error is None


def test_step_failure_marks_failed_and_notifies(db, monkeypatch):
    item = _item(db)
    notes = []

    def _boom(*a, **k):
        raise RenderStepError("step 2 (click #go): timeout", 2, "/tmp/shot.png")

    monkeypatch.setattr(worker, "_render_segments", _boom)
    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert "step 2" in item.render_error
    assert notes and "render failed" in notes[0].lower()


def test_unknown_item_is_a_noop(db):
    worker.render_item(db, "does-not-exist", notify=lambda m: None)   # must not raise
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_render_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: app.video.worker`.

- [ ] **Step 3: Implement**

`backend/app/video/worker.py`:

```python
import os
import tempfile

from app.config import get_settings
from app.db import SessionLocal
from app.media import get_store
from app.models import ContentItem
from app.notify import line_notify
from app.state import InvalidTransition, transition
from app.strategy import load_strategy
from app.video.compose import compose
from app.video.demo import RenderStepError, render_demo
from app.video.scenario import ScenarioError, load_scenario
from app.video.tips import render_tips, write_tips

SCENARIO_ROOT = os.environ.get("SCENARIO_ROOT", "./scenarios")


def _render_segments(item: ContentItem, work_dir: str):
    """Returns (segments, hook_text)."""
    settings = get_settings()
    if item.format == "demo":
        scenario = load_scenario(item.scenario or "", SCENARIO_ROOT)
        login = (
            (settings.demo_email, settings.demo_password)
            if scenario.login and settings.demo_email
            else None
        )
        segments = render_demo(
            scenario, work_dir, base_url="https://eduverse.one/th", login=login
        )
        return segments, item.hook or ""
    if item.format == "tips":
        tips = write_tips(item.topic, load_strategy(settings.strategy_path))
        return render_tips(tips, work_dir), item.hook or tips.hook
    raise ValueError(f"format {item.format} is not renderable")


def render_item(session, item_id: str, notify=line_notify) -> None:
    item = session.get(ContentItem, item_id)
    if item is None:
        return

    with tempfile.TemporaryDirectory(prefix="render-") as work_dir:
        try:
            segments, hook = _render_segments(item, work_dir)
            mp4, poster = compose(segments, hook, work_dir)
            store = get_store(get_settings())
            with open(mp4, "rb") as f:
                item.media_path = store.save(f, "video.mp4")
            with open(poster, "rb") as f:
                store.save(f, "poster.jpg")
            item.render_error = None
            transition(item, "in_review")
        except (RenderStepError, ScenarioError, InvalidTransition, ValueError, Exception) as exc:
            item.render_error = str(exc)[:2000]
            if item.status == "rendering":
                transition(item, "failed")
            notify(f"[AutoMarketing] render failed for {item.slug}: {str(exc)[:300]}")
        finally:
            session.commit()


def main() -> None:
    item_id = os.environ["ITEM_ID"]
    with SessionLocal() as session:
        render_item(session, item_id)
        session.commit()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/test_render_worker.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: render worker — dispatch by format, store media, fail loudly"
```

---

### Task 9: RenderDispatcher + render endpoint + stuck-render sweep

**Files:**
- Create: `backend/app/video/dispatcher.py`
- Modify: `backend/app/api/items.py`, `backend/app/publisher.py`
- Test: `backend/tests/test_dispatcher.py`, `backend/tests/test_render_api.py`, `backend/tests/test_publisher.py` (extend)

**Interfaces:**
- Produces: `app.video.dispatcher.RenderDispatcher` (Protocol: `dispatch(item_id: str) -> None`), `CloudRunDispatcher(settings)`, `LocalDispatcher()`, `get_dispatcher(settings) -> RenderDispatcher`; endpoint `POST /api/items/{id}/render` body `{"format": "demo"|"tips", "scenario": str|None}`; `app.publisher.RENDER_MAX_AGE` and a sweep inside `run_tick` adding `"render_failed"` to the report.
- `item_json` gains `scenario` and `render_error` keys (frontend contract).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_dispatcher.py`:

```python
from app.config import Settings
from app.video.dispatcher import CloudRunDispatcher, LocalDispatcher, get_dispatcher


def test_get_dispatcher_selects_by_setting():
    assert isinstance(get_dispatcher(Settings(render_dispatcher="local")), LocalDispatcher)
    assert isinstance(get_dispatcher(Settings(render_dispatcher="cloudrun")), CloudRunDispatcher)


def test_cloudrun_dispatch_builds_expected_job_path(monkeypatch):
    settings = Settings(render_dispatcher="cloudrun", gcp_project="p",
                        render_job_region="asia-southeast1", render_job_name="automarketing-render")
    captured = {}

    class FakeJobs:
        def run_job(self, request):
            captured["request"] = request

    monkeypatch.setattr(CloudRunDispatcher, "_client", lambda self: FakeJobs())
    CloudRunDispatcher(settings).dispatch("item123")

    req = captured["request"]
    assert req["name"] == "projects/p/locations/asia-southeast1/jobs/automarketing-render"
    override = req["overrides"]["container_overrides"][0]
    assert {"name": "ITEM_ID", "value": "item123"} in override["env"]
```

`backend/tests/test_render_api.py`:

```python
import pytest

import app.api.items as items_api
from tests.test_items_api import AUTH, _create      # reuse Phase 1 helpers


@pytest.fixture(autouse=True)
def fake_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(items_api, "get_dispatcher",
                        lambda s: type("D", (), {"dispatch": lambda self, i: calls.append(i)})())
    return calls


def test_render_moves_item_to_rendering_and_dispatches(client_with_db, fake_dispatch):
    item = _create(client_with_db).json()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/render",
        json={"format": "demo", "scenario": "fixture-demo"}, headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rendering"
    assert body["scenario"] == "fixture-demo"
    assert fake_dispatch == [item["id"]]


def test_demo_without_scenario_is_422(client_with_db):
    item = _create(client_with_db).json()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/render", json={"format": "demo"}, headers=AUTH
    )
    assert resp.status_code == 422


def test_unknown_scenario_is_422(client_with_db):
    item = _create(client_with_db).json()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/render",
        json={"format": "demo", "scenario": "no-such-scenario"}, headers=AUTH,
    )
    assert resp.status_code == 422


def test_render_from_posted_item_is_409(client_with_db, db):
    from app.models import ContentItem
    item = ContentItem(slug="s", topic="t", status="posted")
    db.add(item); db.commit()
    resp = client_with_db.post(
        f"/api/items/{item.id}/render", json={"format": "tips"}, headers=AUTH
    )
    assert resp.status_code == 409
```

Append to `backend/tests/test_publisher.py`:

```python
def test_stuck_render_is_swept_to_failed(db):
    from datetime import timedelta
    item = ContentItem(slug="w32-demo-stuck", topic="t", status="rendering")
    item.updated_at = NOW - timedelta(minutes=25)
    db.add(item); db.commit()
    notes = []

    report = run_tick(db, {}, NOW, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert report["render_failed"] == 1
    assert notes and "stuck" in notes[0].lower()


def test_recent_render_is_left_alone(db):
    from datetime import timedelta
    item = ContentItem(slug="w32-demo-fresh", topic="t", status="rendering")
    item.updated_at = NOW - timedelta(minutes=3)
    db.add(item); db.commit()

    run_tick(db, {}, NOW, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "rendering"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_dispatcher.py tests/test_render_api.py tests/test_publisher.py -v`
Expected: FAIL — missing module `app.video.dispatcher`, missing route, missing `render_failed` key.

- [ ] **Step 3: Implement the dispatcher**

`backend/app/video/dispatcher.py`:

```python
from typing import Protocol

from app.config import Settings


class RenderDispatcher(Protocol):
    def dispatch(self, item_id: str) -> None: ...


class CloudRunDispatcher:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        from google.cloud import run_v2

        return run_v2.JobsClient()

    def dispatch(self, item_id: str) -> None:
        s = self.settings
        name = f"projects/{s.gcp_project}/locations/{s.render_job_region}/jobs/{s.render_job_name}"
        self._client().run_job(
            request={
                "name": name,
                "overrides": {
                    "container_overrides": [
                        {"env": [{"name": "ITEM_ID", "value": item_id}]}
                    ]
                },
            }
        )


class LocalDispatcher:
    """Runs the worker in a subprocess — used in dev and tests."""

    def dispatch(self, item_id: str) -> None:
        import subprocess
        import sys

        subprocess.Popen(
            [sys.executable, "-m", "app.video.worker"],
            env={**__import__("os").environ, "ITEM_ID": item_id},
        )


def get_dispatcher(settings: Settings) -> RenderDispatcher:
    if settings.render_dispatcher == "local":
        return LocalDispatcher()
    return CloudRunDispatcher(settings)
```

Add `"google-cloud-run>=0.10"` to `backend/pyproject.toml` dependencies.

- [ ] **Step 4: Implement the endpoint**

In `backend/app/api/items.py`, add imports:

```python
from app.video.dispatcher import get_dispatcher
from app.video.scenario import ScenarioError, load_scenario
```

Add `"scenario": item.scenario` and `"render_error": item.render_error` to the dict returned by `item_json`, then append the route:

```python
RENDERABLE_FORMATS = {"demo", "tips"}
SCENARIO_ROOT = os.environ.get("SCENARIO_ROOT", "./scenarios")


class RenderBody(BaseModel):
    format: str
    scenario: str | None = None


@router.post("/items/{item_id}/render")
def render(item_id: str, body: RenderBody, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    if body.format not in RENDERABLE_FORMATS:
        raise HTTPException(422, f"format must be one of: {', '.join(sorted(RENDERABLE_FORMATS))}")
    if body.format == "demo":
        if not body.scenario:
            raise HTTPException(422, "demo format requires a scenario")
        try:
            load_scenario(body.scenario, SCENARIO_ROOT)
        except ScenarioError as exc:
            raise HTTPException(422, str(exc))
    try:
        transition(item, "rendering")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    item.format = body.format
    item.scenario = body.scenario
    item.render_error = None
    session.flush()
    get_dispatcher(get_settings()).dispatch(item.id)
    return item_json(item)
```

(`import os` is already present at the top of the file from Phase 1; add it if not.)

- [ ] **Step 5: Implement the stuck-render sweep**

In `backend/app/publisher.py`, add near `PENDING_MAX_AGE`:

```python
RENDER_MAX_AGE = timedelta(minutes=20)
```

Add `"render_failed": 0` to the `report` dict in `run_tick`, and after the publication loop (before `session.flush()`):

```python
    stuck = session.scalars(
        select(ContentItem).where(ContentItem.status == "rendering")
    ).all()
    for item in stuck:
        if now - _aware(item.updated_at) <= RENDER_MAX_AGE:
            continue
        item.render_error = "render timed out"
        transition(item, "failed")
        report["render_failed"] += 1
        notify(f"[AutoMarketing] render stuck over 20 min, failed: {item.slug}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest -q`
Expected: PASS — all Phase 1 tests plus the new dispatcher, API and sweep tests.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: render dispatcher, render endpoint, stuck-render sweep"
```

---

### Task 10: Frontend — format picker and render button

**Files:**
- Modify: `frontend/components/ItemCard.tsx`, `frontend/app/new/page.tsx`
- Test: manual (no component harness exists in this project)

**Interfaces:**
- Consumes: `POST /api/items/{id}/render`, and the `scenario` / `render_error` keys added to `item_json` in Task 9.

- [ ] **Step 1: Extend the Item type**

In `frontend/components/ItemCard.tsx`, add to the `Item` type:

```typescript
  scenario: string | null;
  render_error: string | null;
```

- [ ] **Step 2: Add the render control**

Insert into `ItemCard`, directly above the existing `item.status === "in_review"` block:

```tsx
      {(item.status === "idea" || item.status === "failed") && !item.media_url && (
        <div className="space-y-2 rounded border border-dashed p-3">
          <p className="text-sm font-medium">สร้างวิดีโออัตโนมัติ</p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="rounded border p-2 text-sm"
              value={fmt}
              onChange={(e) => setFmt(e.target.value)}
            >
              <option value="demo">เดโมสินค้า</option>
              <option value="tips">การ์ดเคล็ดลับ</option>
            </select>
            {fmt === "demo" && (
              <input
                className="rounded border p-2 text-sm"
                placeholder="ชื่อ scenario เช่น tgat-demo"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              />
            )}
            <button
              disabled={busy || (fmt === "demo" && !scenario)}
              className="rounded bg-indigo-600 px-3 py-2 text-sm text-white disabled:opacity-40"
              onClick={() =>
                act(() =>
                  apiFetch(`/api/items/${item.id}/render`, {
                    method: "POST",
                    body: JSON.stringify({
                      format: fmt,
                      scenario: fmt === "demo" ? scenario : null,
                    }),
                  })
                )
              }
            >
              สร้างวิดีโอ
            </button>
          </div>
        </div>
      )}
      {item.status === "rendering" && (
        <p className="text-sm text-indigo-600">กำลังสร้างวิดีโอ… (ปกติ 2–5 นาที)</p>
      )}
      {item.render_error && (
        <p className="text-sm text-red-600">เรนเดอร์ล้มเหลว: {item.render_error}</p>
      )}
```

Add the two state hooks beside the existing ones at the top of the component:

```tsx
  const [fmt, setFmt] = useState("demo");
  const [scenario, setScenario] = useState(item.scenario ?? "");
```

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build`
Expected: compiles clean, no TypeScript errors.

- [ ] **Step 4: Manual smoke against a local backend**

With the backend running and `RENDER_DISPATCHER=local`, create an item without a file, choose การ์ดเคล็ดลับ, tap สร้างวิดีโอ, and confirm the card shows `rendering` and then a playable video (or a red `render_error`).

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: render controls in the review queue"
```

---

### Task 11: Render image and deploy

**Files:**
- Create: `render/Dockerfile`
- Modify: `cloudbuild.yaml`, `docs/DEPLOY.md`

**Interfaces:** none new — packages Tasks 2–8 as the `automarketing-render` Cloud Run Job.

- [ ] **Step 1: Write the render image**

`render/Dockerfile` (build context = repo root, like the backend image):

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

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
```

Verify the Thai font path the composer uses exists in this image:

```bash
docker build -f render/Dockerfile -t am-render .
docker run --rm am-render ls /usr/share/fonts/truetype/noto/ | grep -i thai
```

Expected: a `NotoSansThai-Regular.ttf` entry. If the filename differs, update `FONT` in `backend/app/video/compose.py` to match and re-run the Task 5 test.

- [ ] **Step 2: Add the image to Cloud Build**

In `cloudbuild.yaml`, add a build+push step pair mirroring the backend's, with `-f render/Dockerfile` and context `.`, tagging `${_REGION}-docker.pkg.dev/$PROJECT_ID/${_REPO}/render:$BUILD_ID` and `:latest`, and add both tags to the `images:` list.

- [ ] **Step 3: Create the job (one-time) and document it**

Append to `docs/DEPLOY.md` a "Render job" section with:

```bash
gcloud run jobs create automarketing-render \
  --image="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/render:latest" \
  --region="$REGION" --project="$PROJECT" \
  --cpu=2 --memory=4Gi --task-timeout=15m --max-retries=0 \
  --network=default --subnet=default --vpc-egress=private-ranges-only \
  --set-env-vars="^##^DATABASE_URL=<same private-IP url as the backend>##MEDIA_BACKEND=gcs##GCS_BUCKET=${BUCKET}##MEDIA_ROOT=/tmp##CAPTION_PROVIDER=gemini" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,DEMO_EMAIL=DEMO_EMAIL:latest,DEMO_PASSWORD=DEMO_PASSWORD:latest"

# backend needs permission to start it, and its own new env
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/run.developer

gcloud run services update "$BACKEND_SVC" --region="$REGION" --project="$PROJECT" \
  --update-env-vars="RENDER_DISPATCHER=cloudrun,GCP_PROJECT=${PROJECT},RENDER_JOB_NAME=automarketing-render,RENDER_JOB_REGION=${REGION}"
```

Document in the same section that `DEMO_EMAIL` / `DEMO_PASSWORD` are a **production account with credits**, created by the founder, and that each demo render consumes credits.

- [ ] **Step 4: Run the migration in production**

```bash
gcloud run jobs update automarketing-migrate --region="$REGION" --project="$PROJECT" \
  --image="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/backend:latest"
gcloud run jobs execute automarketing-migrate --region="$REGION" --project="$PROJECT" --wait
```

Expected: alembic logs `Running upgrade 0001 -> 0002`.

- [ ] **Step 5: Production verification**

Create an item via the API with no file, `POST /api/items/{id}/render` with `{"format": "tips"}`, and confirm within ~5 minutes that the item reaches `in_review` with a playable `media_url`. Then run one `demo` render against a real scenario and watch it end-to-end. A failure must leave a readable `render_error` and a LINE alert.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: render image, cloud build step, render job runbook"
```

---

## Self-review notes

- **Spec coverage:** §3 architecture (Tasks 8–9, 11), §4.1 scenarios (Task 2), §4.2 DemoRenderer (Task 6), §4.3 TipsRenderer (Task 7), §4.4 KaveeVoice (Task 3), §4.5 Composer (Tasks 4–5), §4.6 RenderDispatcher (Task 9), §5 data model and state (Task 1), §6 error handling (Tasks 6, 8, 9 — screenshot, error tails, stuck sweep, LINE alerts), §7 testing (unit tests throughout; the golden render is `test_compose_produces_vertical_mp4_with_audio_and_poster` plus the fixture-page demo test in Task 6), §8 operational requirements (Task 11 Step 3).
- **Deliberate scope cuts, stated not silent:** no render-history table (the item row carries `render_error`; a job that never starts is caught by the sweep); no component-test harness for the frontend (none exists in this project — Task 10 is build-verified and manually smoked); UI blips are two synthesized tones rather than a designed sound set.
- **Type consistency check:** `Segment(clip_path, narration, fit, sound)` is constructed identically in Tasks 6, 7 and consumed in 5, 8. `Narration(text, path, seconds)` is produced in Task 3 and consumed in 5, 6, 7, 8. `render_item(session, item_id, notify)` in Task 8 is called by `LocalDispatcher` (via `__main__`) and the tests in Task 8. `get_dispatcher(settings)` in Task 9 is patched by name in `test_render_api.py`.
- **Known environmental dependency:** Tasks 4–7 need `ffmpeg` and Playwright's Chromium locally. Tests that render real media are marked `slow`; the render image (Task 11) is the reference environment.
