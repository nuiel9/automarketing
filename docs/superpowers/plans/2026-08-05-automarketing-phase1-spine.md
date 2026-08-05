# AutoMarketing Phase 1 "Spine" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-channel auto-posting pipeline: founder uploads a clip → Claude writes per-platform Thai captions → human review queue → scheduled auto-publish to Facebook, Instagram, X, and LINE OA with UTM links, retries, and failure alerts.

**Architecture:** FastAPI + SQLAlchemy/Postgres backend and a Next.js review-queue frontend, in one repo. A publisher tick (Cloud Scheduler → `/internal/tick`) drains due publications through a `ChannelAdapter` interface (Meta, X, LINE, DryRun). Media is stored via a `MediaStore` (local disk in dev, GCS in prod) and served publicly at unguessable URLs so platforms can fetch video by URL.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Postgres 16 (SQLite in unit tests), httpx + respx (tests), authlib (X OAuth1), anthropic SDK (`claude-opus-5`, structured outputs), PyYAML, google-cloud-storage; Next.js (App Router) + TypeScript + Tailwind.

## Global Constraints

- Python ≥ 3.12; Node ≥ 20.
- LLM calls: model string exactly `claude-opus-5`; use `client.messages.parse` with a Pydantic schema; never parse free text JSON.
- All user-facing marketing copy is Thai; code, comments, and commit messages are English.
- Nothing publishes without an `approved` item and a `pending` publication row — no direct-post code paths.
- Every outbound content link must go through `with_utm()` (utm_source=channel, utm_medium=social, utm_campaign=slug).
- Secrets only via environment variables (never committed); `.env.example` documents every variable.
- Statuses (item): `idea|planned|rendering|in_review|approved|scheduled|posted|rejected|failed` — Phase 1 uses the subset without `planned|rendering`.
- Statuses (publication): `pending|pending_external|posted|failed`.
- Channels enum (strings): `facebook|instagram|x|line|tiktok|youtube|dryrun`. Phase 1 adapters: facebook, instagram, x, line, dryrun. Captions are generated for all six real channels (tiktok/youtube posted manually until Phase 2).
- Commit after every green test cycle. Conventional commit prefixes (`feat:`, `test:`, `chore:`, `docs:`).

---

### Task 0: Backend scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`
- Create: `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`
- Create: `docker-compose.yml`, `.gitignore`, `.env.example`

**Interfaces:**
- Produces: `app.config.Settings` (pydantic-settings; fields below), `app.config.get_settings()` (cached), `app.main.create_app() -> FastAPI`. Every later task imports these.

- [ ] **Step 1: Write project files**

`backend/pyproject.toml`:

```toml
[project]
name = "automarketing"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "psycopg[binary]>=3.2",
  "pydantic-settings>=2.4",
  "httpx>=0.27",
  "authlib>=1.3",
  "anthropic>=0.40",
  "pyyaml>=6.0",
  "google-cloud-storage>=2.18",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21", "aiosqlite>=0.20"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`backend/app/config.py`:

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://automarketing:automarketing@localhost:5433/automarketing"
    admin_token: str = "dev-admin-token"
    tick_token: str = "dev-tick-token"
    public_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:3000"

    media_backend: str = "local"          # "local" | "gcs"
    media_root: str = "./media"           # local backend
    gcs_bucket: str = ""                  # gcs backend

    strategy_path: str = "./strategy.yaml"
    anthropic_api_key: str = ""

    enabled_channels: str = "dryrun"      # comma-separated: facebook,instagram,x,line,dryrun

    meta_page_id: str = ""
    meta_ig_user_id: str = ""
    meta_access_token: str = ""

    x_consumer_key: str = ""
    x_consumer_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""

    line_channel_access_token: str = ""
    line_founder_user_id: str = ""        # failure alerts go here

    def channels(self) -> list[str]:
        return [c.strip() for c in self.enabled_channels.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AutoMarketing")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

`docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: automarketing
      POSTGRES_PASSWORD: automarketing
      POSTGRES_DB: automarketing
    ports: ["5433:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes:
  pgdata:
```

`.gitignore`: `__pycache__/`, `.env`, `media/`, `node_modules/`, `.next/`, `*.egg-info/`, `.pytest_cache/`

`.env.example`: one line per `Settings` field with placeholder values and a comment for each (copy field list above; real values documented further in `docs/PLATFORM_SETUP.md`, Task 14).

- [ ] **Step 2: Write the failing test**

`backend/tests/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())
```

`backend/tests/test_health.py`:

```python
def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 3: Install and run test**

Run: `cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest tests/test_health.py -v`
Expected: PASS (scaffold is trivially green; the failing-first cycle starts with real logic in Task 1).

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: backend scaffold (FastAPI, config, compose, pytest)"
```

---

### Task 1: Database models + migration

**Files:**
- Create: `backend/app/db.py`, `backend/app/models.py`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_init.py`
- Test: `backend/tests/test_models.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces: `app.db.SessionLocal`, `app.db.get_session` (FastAPI dependency), `app.models.Base`, `ContentItem`, `Caption`, `Publication`, `ChannelState` with the exact columns below. All later tasks use these names.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_models.py`:

```python
from datetime import datetime, timezone

from app.models import Caption, ContentItem, Publication


def test_item_caption_publication_roundtrip(db):
    item = ContentItem(slug="w32-clip-tgat", topic="TGAT คณิต", status="idea")
    item.captions.append(Caption(channel="facebook", body="ทดสอบ", hashtags=["#TGAT"]))
    item.publications.append(
        Publication(channel="facebook", scheduled_at=datetime.now(timezone.utc))
    )
    db.add(item)
    db.commit()

    loaded = db.get(ContentItem, item.id)
    assert loaded.captions[0].hashtags == ["#TGAT"]
    assert loaded.publications[0].status == "pending"
    assert loaded.publications[0].attempts == 0
```

Add a `db` fixture to `backend/tests/conftest.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: FAIL (`ModuleNotFoundError: app.models`)

- [ ] **Step 3: Implement**

`backend/app/db.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_session():
    with SessionLocal() as session:
        yield session
        session.commit()
```

`backend/app/models.py`:

```python
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(20), default="founder_clip")
    topic: Mapped[str] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idea")
    media_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_token: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True, default=lambda: secrets.token_urlsafe(16)
    )
    channels: Mapped[list] = mapped_column(JSON, default=list)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    captions: Mapped[list["Caption"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    publications: Mapped[list["Publication"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class Caption(Base):
    __tablename__ = "captions"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"))
    channel: Mapped[str] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False)

    item: Mapped[ContentItem] = relationship(back_populates="captions")


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"))
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    post_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    item: Mapped[ContentItem] = relationship(back_populates="publications")


class ChannelState(Base):
    __tablename__ = "channel_state"

    channel: Mapped[str] = mapped_column(String(20), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto|draft|private|disabled
    needs_reauth: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Alembic migration**

`backend/alembic.ini`: default from `alembic init alembic`, set `sqlalchemy.url` to the compose Postgres URL (env override in `env.py`). In `backend/alembic/env.py` set `target_metadata = Base.metadata` (import from `app.models`) and read `DATABASE_URL` env var when present. Generate:

```bash
docker compose up -d db
cd backend && .venv/bin/alembic revision --autogenerate -m "init" && .venv/bin/alembic upgrade head
```

Verify: `docker compose exec db psql -U automarketing -c '\dt'` lists the four tables.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: core data model (items, captions, publications, channel_state) + migration"
```

---

### Task 2: State machine

**Files:**
- Create: `backend/app/state.py`
- Test: `backend/tests/test_state.py`

**Interfaces:**
- Produces: `app.state.transition(item: ContentItem, to: str) -> None` (raises `app.state.InvalidTransition`), `app.state.ITEM_TRANSITIONS: dict[str, set[str]]`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_state.py`:

```python
import pytest

from app.models import ContentItem
from app.state import InvalidTransition, transition


def make(status: str) -> ContentItem:
    return ContentItem(slug="s", topic="t", status=status)


@pytest.mark.parametrize(
    "src,dst",
    [
        ("idea", "in_review"),
        ("in_review", "approved"),
        ("in_review", "rejected"),
        ("approved", "scheduled"),
        ("scheduled", "posted"),
        ("scheduled", "failed"),
        ("failed", "scheduled"),
        ("rejected", "in_review"),
    ],
)
def test_valid_transitions(src, dst):
    item = make(src)
    transition(item, dst)
    assert item.status == dst


@pytest.mark.parametrize("src,dst", [("idea", "posted"), ("posted", "idea"), ("rejected", "approved")])
def test_invalid_transitions_raise(src, dst):
    with pytest.raises(InvalidTransition):
        transition(make(src), dst)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_state.py -v` — Expected: FAIL (import error)

- [ ] **Step 3: Implement**

`backend/app/state.py`:

```python
from app.models import ContentItem

ITEM_TRANSITIONS: dict[str, set[str]] = {
    "idea": {"in_review"},
    "planned": {"rendering", "rejected"},      # Phase 2+
    "rendering": {"in_review", "failed"},      # Phase 2+
    "in_review": {"approved", "rejected"},
    "approved": {"scheduled"},
    "scheduled": {"posted", "failed"},
    "posted": set(),
    "failed": {"scheduled"},
    "rejected": {"in_review"},
}


class InvalidTransition(Exception):
    pass


def transition(item: ContentItem, to: str) -> None:
    allowed = ITEM_TRANSITIONS.get(item.status, set())
    if to not in allowed:
        raise InvalidTransition(f"{item.status} -> {to} not allowed")
    item.status = to
```

- [ ] **Step 4: Run test** — Expected: PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: content item state machine"`

---

### Task 3: UTM builder + campaign slug

**Files:**
- Create: `backend/app/utm.py`
- Test: `backend/tests/test_utm.py`

**Interfaces:**
- Produces: `app.utm.campaign_slug(fmt: str, topic: str, on: date) -> str` and `app.utm.with_utm(url: str, channel: str, campaign: str) -> str`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_utm.py`:

```python
from datetime import date
from urllib.parse import parse_qs, urlparse

from app.utm import campaign_slug, with_utm


def test_campaign_slug_ascii_and_week():
    slug = campaign_slug("founder_clip", "TGAT คณิต ep.1", date(2026, 8, 5))
    assert slug == "w32-founder-clip-tgat-ep-1"  # Thai chars dropped, ascii kebab


def test_with_utm_adds_params_and_keeps_existing():
    url = with_utm("https://eduverse.one/signup?ref=a", "tiktok", "w32-demo-tgat")
    q = parse_qs(urlparse(url).query)
    assert q["ref"] == ["a"]
    assert q["utm_source"] == ["tiktok"]
    assert q["utm_medium"] == ["social"]
    assert q["utm_campaign"] == ["w32-demo-tgat"]
```

- [ ] **Step 2: Run to verify FAIL**, then **Step 3: Implement**

`backend/app/utm.py`:

```python
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _kebab(text: str) -> str:
    ascii_only = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return re.sub(r"-+", "-", ascii_only).strip("-").lower()


def campaign_slug(fmt: str, topic: str, on: date) -> str:
    week = on.isocalendar().week
    return f"w{week}-{_kebab(fmt)}-{_kebab(topic)}"


def with_utm(url: str, channel: str, campaign: str) -> str:
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query))
    query.update(
        {"utm_source": channel, "utm_medium": "social", "utm_campaign": campaign}
    )
    return urlunparse(parts._replace(query=urlencode(query)))
```

- [ ] **Step 4: Run test** — Expected: PASS. **Step 5: Commit** `feat: utm builder and campaign slugs`

---

### Task 4: Strategy config + banned-words gate

**Files:**
- Create: `strategy.yaml` (repo root), `backend/app/strategy.py`
- Test: `backend/tests/test_strategy.py`

**Interfaces:**
- Produces: `app.strategy.Strategy` (pydantic model: `voice: str`, `audiences: list[str]`, `banned_words: list[str]`, `platform_notes: dict[str, str]`), `app.strategy.load_strategy(path) -> Strategy`, `app.strategy.banned_violations(strategy, texts: list[str]) -> list[str]`.

- [ ] **Step 1: Write `strategy.yaml`**

```yaml
voice: >
  เป็นกันเอง จริงใจ ไม่ขายของแข็ง ๆ พูดเหมือนรุ่นพี่ติวให้รุ่นน้อง
  หลีกเลี่ยงคำเวอร์เกินจริง เน้นให้เห็นของจริงจากตัวแอป
audiences:
  - นักเรียนเตรียมสอบ TGAT/TPAT/A-Level และผู้ปกครอง
  - นักศึกษามหาวิทยาลัย (ABAC เป็นหัวหาด)
  - วัยทำงานอัปสกิล (ภาษาอังกฤษ, Excel, การเงิน)
banned_words:
  - รับประกันสอบติด
  - ดีที่สุดในประเทศ
  - ฟรีตลอดชีพ
platform_notes:
  tiktok: "แคปชันสั้น ติดแฮชแท็ก #DEK69 #TCAS ได้เมื่อเกี่ยวข้อง"
  youtube: "ตั้ง title ให้ค้นเจอ (คีย์เวิร์ดข้อสอบ/วิชา) description มีลิงก์"
  instagram: "แคปชันอ่านง่าย เว้นบรรทัด ใส่แฮชแท็กท้ายโพสต์"
  facebook: "พูดกับผู้ปกครองได้ด้วย น้ำเสียงอบอุ่น"
  x: "สั้น กระชับ ไม่เกิน 280 ตัวอักษร"
  line: "ข้อความบรอดแคสต์ สุภาพ มีลิงก์ชัดเจน ไม่สแปม"
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_strategy.py`:

```python
from app.strategy import banned_violations, load_strategy


def test_load_strategy_and_gate(tmp_path):
    p = tmp_path / "strategy.yaml"
    p.write_text(
        "voice: v\naudiences: [a]\nbanned_words: [รับประกันสอบติด]\nplatform_notes: {x: n}\n",
        encoding="utf-8",
    )
    s = load_strategy(str(p))
    assert s.voice == "v"
    assert banned_violations(s, ["เรารับประกันสอบติดแน่นอน"]) == ["รับประกันสอบติด"]
    assert banned_violations(s, ["ข้อความปกติ"]) == []
```

- [ ] **Step 3: Run FAIL, implement**

`backend/app/strategy.py`:

```python
import yaml
from pydantic import BaseModel


class Strategy(BaseModel):
    voice: str
    audiences: list[str]
    banned_words: list[str]
    platform_notes: dict[str, str]


def load_strategy(path: str) -> Strategy:
    with open(path, encoding="utf-8") as f:
        return Strategy.model_validate(yaml.safe_load(f))


def banned_violations(strategy: Strategy, texts: list[str]) -> list[str]:
    joined = "\n".join(t for t in texts if t)
    return [w for w in strategy.banned_words if w in joined]
```

- [ ] **Step 4: Run test** — PASS. **Step 5: Commit** `feat: strategy config and banned-words gate`

---

### Task 5: Media store + public media route

**Files:**
- Create: `backend/app/media.py`, `backend/app/api/__init__.py`, `backend/app/api/media.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_media.py`

**Interfaces:**
- Produces: `app.media.MediaStore` protocol (`save(data: BinaryIO, filename: str) -> str`, `open(path: str) -> BinaryIO`), `LocalMediaStore(root)`, `GCSMediaStore(bucket)`, `app.media.get_store(settings) -> MediaStore`, and public route `GET /media/{token}` streaming `video/mp4`. Publisher (Task 9) builds media URLs as `{public_base_url}/media/{item.media_token}`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_media.py`:

```python
import io

from app.media import LocalMediaStore
from app.models import ContentItem


def test_local_store_roundtrip(tmp_path):
    store = LocalMediaStore(str(tmp_path))
    path = store.save(io.BytesIO(b"fake-mp4"), "clip.mp4")
    assert store.open(path).read() == b"fake-mp4"


def test_media_route_streams_by_token(client_with_db, db, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "media_root", str(tmp_path))
    store = LocalMediaStore(str(tmp_path))
    path = store.save(io.BytesIO(b"vid"), "clip.mp4")
    item = ContentItem(slug="s", topic="t", media_path=path)
    db.add(item)
    db.commit()

    resp = client_with_db.get(f"/media/{item.media_token}")
    assert resp.status_code == 200
    assert resp.content == b"vid"

    assert client_with_db.get("/media/nope").status_code == 404
```

Add `client_with_db` to `conftest.py` — a `TestClient` whose app has `get_session` overridden to yield the sqlite `db` fixture session:

```python
@pytest.fixture
def client_with_db(db):
    from app.db import get_session
    app = create_app()
    app.dependency_overrides[get_session] = lambda: (yield db)
    return TestClient(app)
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/media.py`:

```python
import os
import uuid
from typing import BinaryIO, Protocol

from app.config import Settings


class MediaStore(Protocol):
    def save(self, data: BinaryIO, filename: str) -> str: ...
    def open(self, path: str) -> BinaryIO: ...


class LocalMediaStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, data: BinaryIO, filename: str) -> str:
        ext = os.path.splitext(filename)[1] or ".mp4"
        rel = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(self.root, rel), "wb") as f:
            while chunk := data.read(1 << 20):
                f.write(chunk)
        return rel

    def open(self, path: str) -> BinaryIO:
        return open(os.path.join(self.root, path), "rb")


class GCSMediaStore:
    def __init__(self, bucket: str):
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)

    def save(self, data: BinaryIO, filename: str) -> str:
        import uuid as _uuid

        ext = os.path.splitext(filename)[1] or ".mp4"
        rel = f"media/{_uuid.uuid4().hex}{ext}"
        self.bucket.blob(rel).upload_from_file(data, content_type="video/mp4")
        return rel

    def open(self, path: str) -> BinaryIO:
        import io

        buf = io.BytesIO()
        self.bucket.blob(path).download_to_file(buf)
        buf.seek(0)
        return buf


def get_store(settings: Settings) -> MediaStore:
    if settings.media_backend == "gcs":
        return GCSMediaStore(settings.gcs_bucket)
    return LocalMediaStore(settings.media_root)
```

`backend/app/api/media.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.media import get_store
from app.models import ContentItem

router = APIRouter()


@router.get("/media/{token}")
def serve_media(token: str, session: Session = Depends(get_session)):
    item = session.scalar(select(ContentItem).where(ContentItem.media_token == token))
    if item is None or not item.media_path:
        raise HTTPException(404)
    store = get_store(get_settings())
    return StreamingResponse(store.open(item.media_path), media_type="video/mp4")
```

In `create_app()`: `from app.api.media import router as media_router` + `app.include_router(media_router)`.

- [ ] **Step 3: Run tests** — PASS. **Step 4: Commit** `feat: media store (local/GCS) and public media route`

---

### Task 6: Caption writer (Claude structured outputs)

**Files:**
- Create: `backend/app/captions.py`
- Test: `backend/tests/test_captions.py`

**Interfaces:**
- Consumes: `Strategy` (Task 4).
- Produces: `app.captions.ChannelCaption` (pydantic: `title: str | None`, `body: str`, `hashtags: list[str]`), `app.captions.CaptionSet` (fields `tiktok, youtube, instagram, facebook, x, line`, each `ChannelCaption`), `app.captions.write_captions(topic, hook, strategy) -> CaptionSet`, `app.captions.CaptionError`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_captions.py`:

```python
import pytest

import app.captions as captions
from app.captions import CaptionError, CaptionSet, ChannelCaption, write_captions
from app.strategy import Strategy

STRATEGY = Strategy(voice="v", audiences=["a"], banned_words=[], platform_notes={})

FAKE = CaptionSet(
    tiktok=ChannelCaption(title=None, body="ติวสอบ", hashtags=["#DEK69"]),
    youtube=ChannelCaption(title="ติว TGAT", body="รายละเอียด", hashtags=[]),
    instagram=ChannelCaption(title=None, body="ig", hashtags=[]),
    facebook=ChannelCaption(title=None, body="fb", hashtags=[]),
    x=ChannelCaption(title=None, body="x", hashtags=[]),
    line=ChannelCaption(title=None, body="line", hashtags=[]),
)


class FakeParsed:
    parsed_output = FAKE


class FakeMessages:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise RuntimeError("api down")
        return FakeParsed()


class FakeClient:
    def __init__(self, fail: bool = False):
        self.messages = FakeMessages(fail)


def test_write_captions_returns_set(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(captions, "_client", lambda: fake)
    result = write_captions("TGAT คณิต", "hook", STRATEGY)
    assert result.tiktok.hashtags == ["#DEK69"]
    assert fake.messages.kwargs["model"] == "claude-opus-5"
    assert "TGAT คณิต" in fake.messages.kwargs["messages"][0]["content"]


def test_write_captions_wraps_errors(monkeypatch):
    monkeypatch.setattr(captions, "_client", lambda: FakeClient(fail=True))
    with pytest.raises(CaptionError):
        write_captions("t", None, STRATEGY)
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/captions.py`:

```python
import anthropic
from pydantic import BaseModel

from app.config import get_settings
from app.strategy import Strategy


class ChannelCaption(BaseModel):
    title: str | None = None
    body: str
    hashtags: list[str] = []


class CaptionSet(BaseModel):
    tiktok: ChannelCaption
    youtube: ChannelCaption
    instagram: ChannelCaption
    facebook: ChannelCaption
    x: ChannelCaption
    line: ChannelCaption


class CaptionError(Exception):
    pass


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


SYSTEM_TEMPLATE = """You write Thai social media copy for Eduverse One,
an AI tutor app where users type a goal or drop a PDF and get a full course
with a Thai voice tutor named Kavee.

Brand voice: {voice}
Audiences: {audiences}
Per-platform notes: {notes}

Rules: natural Thai a real person would post, no hard selling, no invented
features or guarantees. Do NOT include URLs — links are appended by the system.
X body must be under 250 characters. YouTube needs a searchable title."""


def write_captions(topic: str, hook: str | None, strategy: Strategy) -> CaptionSet:
    system = SYSTEM_TEMPLATE.format(
        voice=strategy.voice,
        audiences=", ".join(strategy.audiences),
        notes="; ".join(f"{k}: {v}" for k, v in strategy.platform_notes.items()),
    )
    user = f"Topic: {topic}\nHook: {hook or '-'}\nWrite captions for all six channels."
    try:
        response = _client().messages.parse(
            model="claude-opus-5",
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=CaptionSet,
        )
    except Exception as exc:
        raise CaptionError(str(exc)) from exc
    if response.parsed_output is None:
        raise CaptionError("model returned no parsed output")
    return response.parsed_output
```

- [ ] **Step 3: Run tests** — PASS. **Step 4: Commit** `feat: Claude caption writer with structured outputs`

---

### Task 7: Items API

**Files:**
- Create: `backend/app/api/auth.py`, `backend/app/api/items.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_items_api.py`

**Interfaces:**
- Consumes: `write_captions`, `banned_violations`, `load_strategy`, `transition`, `get_store`, `campaign_slug`.
- Produces: REST API under `/api` (auth: `Authorization: Bearer {admin_token}`):
  - `POST /api/items` (multipart: `topic`, `hook?`, `link?`, `file?`) → creates item; generates captions; status `in_review` (or stays `idea` with `caption_error` in response if the LLM call fails).
  - `POST /api/items/{id}/captions` → (re)generate captions, `idea → in_review`.
  - `GET /api/items?status=...`, `GET /api/items/{id}` → item JSON incl. captions, publications, `media_url`, `banned_violations`.
  - `PUT /api/items/{id}/captions` body `{channel, title, body, hashtags}` → edit (sets `edited_by_human`).
  - `POST /api/items/{id}/approve` body `{scheduled_at, channels}` → validates captions + banned gate; creates `Publication` rows; status `scheduled`.
  - `POST /api/items/{id}/reject` body `{reason}`; `POST /api/items/{id}/retry` (failed → scheduled; failed publications reset).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_items_api.py` (uses `client_with_db`; monkeypatch `app.api.items.write_captions` to return the `FAKE` caption set from Task 6's test, and `load_strategy` to a fixed `Strategy`):

```python
from datetime import datetime, timedelta, timezone

import pytest

import app.api.items as items_api
from app.strategy import Strategy
from tests.test_captions import FAKE

AUTH = {"Authorization": "Bearer dev-admin-token"}
STRATEGY = Strategy(voice="v", audiences=["a"], banned_words=["ห้ามคำนี้"], platform_notes={})


@pytest.fixture(autouse=True)
def patch_deps(monkeypatch):
    monkeypatch.setattr(items_api, "write_captions", lambda topic, hook, strategy: FAKE)
    monkeypatch.setattr(items_api, "load_strategy", lambda path: STRATEGY)


def _create(client, **extra):
    data = {"topic": "TGAT คณิต", "link": "https://eduverse.one", **extra}
    files = {"file": ("clip.mp4", b"fake", "video/mp4")}
    return client.post("/api/items", data=data, files=files, headers=AUTH)


def test_requires_auth(client_with_db):
    assert client_with_db.get("/api/items").status_code == 401


def test_create_generates_captions_and_reviews(client_with_db):
    resp = _create(client_with_db)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "in_review"
    assert {c["channel"] for c in body["captions"]} == {
        "tiktok", "youtube", "instagram", "facebook", "x", "line"
    }
    assert body["media_url"].endswith(body["media_token"])


def test_approve_creates_publications(client_with_db):
    item = _create(client_with_db).json()
    when = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/approve",
        json={"scheduled_at": when, "channels": ["facebook", "x"]},
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "scheduled"
    assert {p["channel"] for p in body["publications"]} == {"facebook", "x"}
    assert all(p["status"] == "pending" for p in body["publications"])


def test_approve_blocked_by_banned_words(client_with_db):
    item = _create(client_with_db).json()
    client_with_db.put(
        f"/api/items/{item['id']}/captions",
        json={"channel": "facebook", "title": None, "body": "มีห้ามคำนี้อยู่", "hashtags": []},
        headers=AUTH,
    )
    when = datetime.now(timezone.utc).isoformat()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/approve",
        json={"scheduled_at": when, "channels": ["facebook"]},
        headers=AUTH,
    )
    assert resp.status_code == 422
    assert "ห้ามคำนี้" in resp.text


def test_reject_and_reopen(client_with_db):
    item = _create(client_with_db).json()
    r = client_with_db.post(
        f"/api/items/{item['id']}/reject", json={"reason": "cringe"}, headers=AUTH
    )
    assert r.json()["status"] == "rejected"
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/api/auth.py`:

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

_scheme = HTTPBearer(auto_error=False)


def require_admin(cred: HTTPAuthorizationCredentials | None = Depends(_scheme)) -> None:
    if cred is None or cred.credentials != get_settings().admin_token:
        raise HTTPException(401, "invalid admin token")
```

`backend/app/api/items.py`:

```python
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.captions import CaptionError, write_captions
from app.config import get_settings
from app.db import get_session
from app.media import get_store
from app.models import Caption, ContentItem, Publication
from app.state import InvalidTransition, transition
from app.strategy import banned_violations, load_strategy
from app.utm import campaign_slug

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])

CHANNELS = ["tiktok", "youtube", "instagram", "facebook", "x", "line"]


def item_json(item: ContentItem) -> dict:
    settings = get_settings()
    strategy = load_strategy(settings.strategy_path)
    return {
        "id": item.id,
        "slug": item.slug,
        "topic": item.topic,
        "hook": item.hook,
        "link": item.link,
        "status": item.status,
        "media_token": item.media_token,
        "media_url": f"{settings.public_base_url}/media/{item.media_token}"
        if item.media_path
        else None,
        "reject_reason": item.reject_reason,
        "banned_violations": banned_violations(
            strategy, [c.body for c in item.captions] + [c.title or "" for c in item.captions]
        ),
        "captions": [
            {
                "channel": c.channel,
                "title": c.title,
                "body": c.body,
                "hashtags": c.hashtags,
                "edited_by_human": c.edited_by_human,
            }
            for c in item.captions
        ],
        "publications": [
            {
                "channel": p.channel,
                "status": p.status,
                "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                "post_ref": p.post_ref,
                "attempts": p.attempts,
                "last_error": p.last_error,
            }
            for p in item.publications
        ],
    }


def _generate(item: ContentItem, session: Session) -> str | None:
    settings = get_settings()
    try:
        caps = write_captions(item.topic, item.hook, load_strategy(settings.strategy_path))
    except CaptionError as exc:
        return str(exc)
    item.captions.clear()
    for channel in CHANNELS:
        c = getattr(caps, channel)
        item.captions.append(
            Caption(channel=channel, title=c.title, body=c.body, hashtags=c.hashtags)
        )
    if item.status == "idea":
        transition(item, "in_review")
    return None


@router.post("/items", status_code=201)
def create_item(
    topic: str = Form(...),
    hook: str | None = Form(None),
    link: str | None = Form(None),
    file: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    item = ContentItem(
        slug=campaign_slug("founder_clip", topic, date.today()),
        topic=topic,
        hook=hook,
        link=link,
    )
    if file is not None:
        item.media_path = get_store(get_settings()).save(file.file, file.filename or "clip.mp4")
    caption_error = _generate(item, session)
    session.add(item)
    session.flush()
    body = item_json(item)
    if caption_error:
        body["caption_error"] = caption_error
    return body


def _get(item_id: str, session: Session) -> ContentItem:
    item = session.get(ContentItem, item_id)
    if item is None:
        raise HTTPException(404)
    return item


@router.post("/items/{item_id}/captions")
def regenerate(item_id: str, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    error = _generate(item, session)
    if error:
        raise HTTPException(502, f"caption generation failed: {error}")
    return item_json(item)


@router.get("/items")
def list_items(status: str | None = None, session: Session = Depends(get_session)):
    q = select(ContentItem).order_by(ContentItem.created_at.desc())
    if status:
        q = q.where(ContentItem.status == status)
    return [item_json(i) for i in session.scalars(q).all()]


@router.get("/items/{item_id}")
def get_item(item_id: str, session: Session = Depends(get_session)):
    return item_json(_get(item_id, session))


class CaptionEdit(BaseModel):
    channel: str
    title: str | None = None
    body: str
    hashtags: list[str] = []


@router.put("/items/{item_id}/captions")
def edit_caption(item_id: str, edit: CaptionEdit, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    for c in item.captions:
        if c.channel == edit.channel:
            c.title, c.body, c.hashtags = edit.title, edit.body, edit.hashtags
            c.edited_by_human = True
            return item_json(item)
    raise HTTPException(404, "no caption for channel")


class ApproveBody(BaseModel):
    scheduled_at: datetime
    channels: list[str]


@router.post("/items/{item_id}/approve")
def approve(item_id: str, body: ApproveBody, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    strategy = load_strategy(get_settings().strategy_path)
    violations = banned_violations(
        strategy, [c.body for c in item.captions] + [c.title or "" for c in item.captions]
    )
    if violations:
        raise HTTPException(422, f"banned words present: {', '.join(violations)}")
    have = {c.channel for c in item.captions}
    missing = [ch for ch in body.channels if ch not in have and ch != "dryrun"]
    if missing:
        raise HTTPException(422, f"no captions for: {', '.join(missing)}")
    try:
        transition(item, "approved")
        transition(item, "scheduled")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    item.channels = body.channels
    for channel in body.channels:
        item.publications.append(
            Publication(channel=channel, scheduled_at=body.scheduled_at)
        )
    return item_json(item)


class RejectBody(BaseModel):
    reason: str


@router.post("/items/{item_id}/reject")
def reject(item_id: str, body: RejectBody, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    try:
        transition(item, "rejected")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    item.reject_reason = body.reason
    return item_json(item)


@router.post("/items/{item_id}/retry")
def retry(item_id: str, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    try:
        transition(item, "scheduled")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    for p in item.publications:
        if p.status == "failed":
            p.status, p.attempts, p.next_attempt_at, p.last_error = "pending", 0, None, None
    return item_json(item)
```

Register in `create_app()`: `app.include_router(items_router)`.

- [ ] **Step 3: Run tests** — `pytest tests/test_items_api.py -v` — PASS
- [ ] **Step 4: Commit** `feat: content items API (create/upload, captions, approve, reject, retry)`

---

### Task 8: Channel adapter contract + DryRunAdapter

**Files:**
- Create: `backend/app/channels/__init__.py`, `backend/app/channels/base.py`, `backend/app/channels/dryrun.py`
- Test: `backend/tests/test_dryrun.py`

**Interfaces:**
- Produces (all later adapter tasks implement exactly this):

```python
# base.py — exact contract
@dataclass
class PublishRequest:
    item_id: str
    channel: str
    title: str | None
    body: str            # final text incl. UTM link, hashtags appended
    media_url: str | None
    state: dict | None   # prior external state (pending_external), else None

@dataclass
class PublishOutcome:
    status: Literal["posted", "pending"]
    post_ref: str | None = None
    state: dict | None = None

class ChannelError(Exception):        # retryable
class ChannelAuthError(ChannelError)  # pauses channel

class ChannelAdapter(Protocol):
    def publish(self, req: PublishRequest) -> PublishOutcome: ...
```

- [ ] **Step 1: Write the failing test**

`backend/tests/test_dryrun.py`:

```python
import json

from app.channels.base import PublishRequest
from app.channels.dryrun import DryRunAdapter


def test_dryrun_appends_jsonl_and_returns_ref(tmp_path):
    adapter = DryRunAdapter(str(tmp_path / "feed.jsonl"))
    req = PublishRequest(
        item_id="abc", channel="dryrun", title=None, body="สวัสดี", media_url=None, state=None
    )
    out1 = adapter.publish(req)
    out2 = adapter.publish(req)
    assert out1.status == "posted" and out1.post_ref == "dryrun-1"
    assert out2.post_ref == "dryrun-2"
    lines = (tmp_path / "feed.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["body"] == "สวัสดี"
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/channels/base.py`: exactly the contract above plus imports (`dataclasses.dataclass`, `typing.Literal, Protocol`).

`backend/app/channels/dryrun.py`:

```python
import json
import os

from app.channels.base import PublishOutcome, PublishRequest


class DryRunAdapter:
    def __init__(self, feed_path: str):
        self.feed_path = feed_path
        os.makedirs(os.path.dirname(feed_path) or ".", exist_ok=True)

    def publish(self, req: PublishRequest) -> PublishOutcome:
        count = 0
        if os.path.exists(self.feed_path):
            with open(self.feed_path, encoding="utf-8") as f:
                count = sum(1 for _ in f)
        with open(self.feed_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"item_id": req.item_id, "body": req.body}, ensure_ascii=False) + "\n")
        return PublishOutcome(status="posted", post_ref=f"dryrun-{count + 1}")
```

- [ ] **Step 3: Run tests** — PASS. **Step 4: Commit** `feat: channel adapter contract and dry-run adapter`

---

### Task 9: Publisher service + tick endpoint + failure notifier

**Files:**
- Create: `backend/app/publisher.py`, `backend/app/notify.py`, `backend/app/channels/registry.py`, `backend/app/api/tick.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_publisher.py`

**Interfaces:**
- Consumes: `ChannelAdapter` contract, models, `with_utm`.
- Produces: `app.publisher.run_tick(session, adapters: dict[str, ChannelAdapter], now: datetime, notify: Callable[[str], None]) -> dict` (report `{"posted": n, "pending": n, "failed": n, "retried": n}`); `app.channels.registry.build_adapters(settings) -> dict[str, ChannelAdapter]`; `app.notify.line_notify(text)`; endpoint `POST /internal/tick` (header `X-Tick-Token`).
- Behavior contract: due = `status IN (pending, pending_external) AND scheduled_at <= now AND (next_attempt_at IS NULL OR next_attempt_at <= now)`, selected `with_for_update(skip_locked=True)`. Backoff: `next_attempt_at = now + 2**attempts minutes`; `attempts >= 3` → `failed` + notify. `ChannelAuthError` → set `ChannelState.needs_reauth`, delay 1h, notify, do not count attempt. `pending` outcome → `pending_external`, store state, re-check in 60s. After processing, parent item becomes `posted` when all its publications are `posted`, `failed` if any `failed`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_publisher.py`:

```python
from datetime import datetime, timedelta, timezone

from app.channels.base import ChannelAuthError, ChannelError, PublishOutcome, PublishRequest
from app.models import Caption, ChannelState, ContentItem, Publication
from app.publisher import run_tick

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


class StubAdapter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[PublishRequest] = []

    def publish(self, req):
        self.requests.append(req)
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def seed(db, channel="dryrun", scheduled=NOW - timedelta(minutes=1)):
    item = ContentItem(
        slug="w32-founder-clip-t", topic="t", status="scheduled",
        link="https://eduverse.one",
    )
    item.captions.append(Caption(channel=channel, body="ตัวอย่าง", hashtags=["#a"]))
    pub = Publication(channel=channel, scheduled_at=scheduled)
    item.publications.append(pub)
    db.add(item)
    db.commit()
    return item, pub


def test_success_posts_and_completes_item(db):
    item, pub = seed(db)
    adapter = StubAdapter([PublishOutcome(status="posted", post_ref="p1")])
    report = run_tick(db, {"dryrun": adapter}, NOW, notify=lambda m: None)
    assert report["posted"] == 1
    assert pub.status == "posted" and pub.post_ref == "p1"
    assert item.status == "posted"
    body = adapter.requests[0].body
    assert "utm_source=dryrun" in body and "utm_campaign=w32-founder-clip-t" in body
    assert "#a" in body


def test_retry_then_fail_notifies(db):
    item, pub = seed(db)
    errors = [ChannelError("boom"), ChannelError("boom"), ChannelError("boom")]
    notes = []
    adapter = StubAdapter(errors)
    t = NOW
    for _ in range(3):
        run_tick(db, {"dryrun": adapter}, t, notify=notes.append)
        t = (pub.next_attempt_at or t) + timedelta(seconds=1)
    assert pub.status == "failed" and pub.attempts == 3
    assert item.status == "failed"
    assert len(notes) == 1 and "dryrun" in notes[0]


def test_pending_external_stores_state_and_resumes(db):
    item, pub = seed(db, channel="instagram")
    adapter = StubAdapter([
        PublishOutcome(status="pending", state={"creation_id": "c9"}),
        PublishOutcome(status="posted", post_ref="ig1"),
    ])
    run_tick(db, {"instagram": adapter}, NOW, notify=lambda m: None)
    assert pub.status == "pending_external" and pub.external_state == {"creation_id": "c9"}
    run_tick(db, {"instagram": adapter}, NOW + timedelta(minutes=2), notify=lambda m: None)
    assert pub.status == "posted"
    assert adapter.requests[1].state == {"creation_id": "c9"}


def test_auth_error_pauses_channel(db):
    item, pub = seed(db, channel="x")
    notes = []
    adapter = StubAdapter([ChannelAuthError("token expired")])
    run_tick(db, {"x": adapter}, NOW, notify=notes.append)
    assert pub.status == "pending" and pub.attempts == 0
    state = db.get(ChannelState, "x")
    assert state is not None and state.needs_reauth is True
    assert len(notes) == 1
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/publisher.py`:

```python
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import or_, select

from app.channels.base import (
    ChannelAdapter, ChannelAuthError, ChannelError, PublishOutcome, PublishRequest,
)
from app.config import get_settings
from app.models import ChannelState, ContentItem, Publication
from app.state import transition
from app.utm import with_utm

MAX_ATTEMPTS = 3


def _build_request(pub: Publication) -> PublishRequest:
    item = pub.item
    caption = next((c for c in item.captions if c.channel == pub.channel), None)
    body_parts = [caption.body if caption else item.topic]
    if caption and caption.hashtags:
        body_parts.append(" ".join(caption.hashtags))
    if item.link:
        body_parts.append(with_utm(item.link, pub.channel, item.slug))
    media_url = (
        f"{get_settings().public_base_url}/media/{item.media_token}"
        if item.media_path
        else None
    )
    return PublishRequest(
        item_id=item.id,
        channel=pub.channel,
        title=caption.title if caption else None,
        body="\n\n".join(body_parts),
        media_url=media_url,
        state=pub.external_state,
    )


def _settle_item(item: ContentItem) -> None:
    statuses = {p.status for p in item.publications}
    if statuses <= {"posted"} and item.status == "scheduled":
        transition(item, "posted")
    elif "failed" in statuses and item.status == "scheduled":
        transition(item, "failed")


def run_tick(
    session,
    adapters: dict[str, ChannelAdapter],
    now: datetime,
    notify: Callable[[str], None],
) -> dict:
    report = {"posted": 0, "pending": 0, "failed": 0, "retried": 0}
    due = session.scalars(
        select(Publication)
        .where(
            Publication.status.in_(["pending", "pending_external"]),
            Publication.scheduled_at <= now,
            or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now),
        )
        .with_for_update(skip_locked=True)
    ).all()

    for pub in due:
        adapter = adapters.get(pub.channel)
        if adapter is None:
            continue
        try:
            outcome: PublishOutcome = adapter.publish(_build_request(pub))
        except ChannelAuthError as exc:
            state = session.get(ChannelState, pub.channel) or ChannelState(channel=pub.channel)
            state.needs_reauth = True
            state.note = str(exc)
            session.merge(state)
            pub.next_attempt_at = now + timedelta(hours=1)
            notify(f"[AutoMarketing] {pub.channel} needs re-auth: {exc}")
            continue
        except ChannelError as exc:
            pub.attempts += 1
            pub.last_error = str(exc)
            if pub.attempts >= MAX_ATTEMPTS:
                pub.status = "failed"
                report["failed"] += 1
                notify(f"[AutoMarketing] publish failed on {pub.channel}: {exc}")
            else:
                pub.next_attempt_at = now + timedelta(minutes=2**pub.attempts)
                report["retried"] += 1
            _settle_item(pub.item)
            continue

        if outcome.status == "posted":
            pub.status = "posted"
            pub.posted_at = now
            pub.post_ref = outcome.post_ref
            report["posted"] += 1
        else:
            pub.status = "pending_external"
            pub.external_state = outcome.state
            pub.next_attempt_at = now + timedelta(seconds=60)
            report["pending"] += 1
        _settle_item(pub.item)

    session.flush()
    return report
```

`backend/app/notify.py`:

```python
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


def line_notify(text: str) -> None:
    settings = get_settings()
    if not (settings.line_channel_access_token and settings.line_founder_user_id):
        log.warning("notify (no LINE configured): %s", text)
        return
    httpx.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {settings.line_channel_access_token}"},
        json={"to": settings.line_founder_user_id,
              "messages": [{"type": "text", "text": text[:4900]}]},
        timeout=10,
    )
```

`backend/app/channels/registry.py`:

```python
import os

from app.channels.base import ChannelAdapter
from app.channels.dryrun import DryRunAdapter
from app.config import Settings


def build_adapters(settings: Settings) -> dict[str, ChannelAdapter]:
    adapters: dict[str, ChannelAdapter] = {}
    for channel in settings.channels():
        if channel == "dryrun":
            adapters["dryrun"] = DryRunAdapter(
                os.path.join(settings.media_root, "dryrun_feed.jsonl")
            )
        elif channel in ("facebook", "instagram"):
            from app.channels.meta import MetaAdapter  # Task 10
            adapters[channel] = MetaAdapter(settings)
        elif channel == "x":
            from app.channels.x import XAdapter  # Task 11
            adapters["x"] = XAdapter(settings)
        elif channel == "line":
            from app.channels.line import LineAdapter  # Task 12
            adapters["line"] = LineAdapter(settings)
    return adapters
```

(Until Tasks 10–12 exist, only `dryrun` is enabled via `ENABLED_CHANNELS=dryrun`, so the lazy imports never fire — the registry stays importable.)

`backend/app/api/tick.py`:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.channels.registry import build_adapters
from app.config import get_settings
from app.db import get_session
from app.notify import line_notify
from app.publisher import run_tick

router = APIRouter()


@router.post("/internal/tick")
def tick(
    x_tick_token: str = Header(default=""),
    session: Session = Depends(get_session),
):
    settings = get_settings()
    if x_tick_token != settings.tick_token:
        raise HTTPException(401)
    return run_tick(
        session,
        build_adapters(settings),
        datetime.now(timezone.utc),
        notify=line_notify,
    )
```

Register `tick.router` in `create_app()`.

- [ ] **Step 3: Run tests** — `pytest tests/test_publisher.py -v` — PASS
- [ ] **Step 4: Full-suite run** — `pytest -q` — all green
- [ ] **Step 5: Commit** `feat: publisher tick with retries, pending-external resume, auth pausing`

---

### Task 10: MetaAdapter (Facebook Page video + Instagram Reels)

**Files:**
- Create: `backend/app/channels/meta.py`
- Test: `backend/tests/test_meta_adapter.py`

**Interfaces:**
- Consumes/Produces: implements `ChannelAdapter`. Facebook: one-shot `posted`. Instagram: two-phase via `pending` state `{"creation_id": ...}` (container create → poll → publish), matching Task 9's resume flow.

- [ ] **Step 1: Write the failing tests** (respx mocks `https://graph.facebook.com`)

`backend/tests/test_meta_adapter.py`:

```python
import pytest
import respx
from httpx import Response

from app.channels.base import ChannelAuthError, ChannelError, PublishRequest
from app.channels.meta import GRAPH, MetaAdapter
from app.config import Settings

SETTINGS = Settings(
    meta_page_id="PAGE", meta_ig_user_id="IGU", meta_access_token="TOK"
)


def req(channel: str, state=None) -> PublishRequest:
    return PublishRequest(
        item_id="i1", channel=channel, title=None, body="แคปชัน",
        media_url="https://app.example/media/tok1", state=state,
    )


@respx.mock
def test_facebook_video_post():
    route = respx.post(f"{GRAPH}/PAGE/videos").mock(
        return_value=Response(200, json={"id": "fb123"})
    )
    out = MetaAdapter(SETTINGS).publish(req("facebook"))
    assert out.status == "posted" and out.post_ref == "fb123"
    sent = route.calls[0].request
    assert b"file_url" in sent.read() and b"TOK" in sent.read()


@respx.mock
def test_instagram_phase1_creates_container():
    respx.post(f"{GRAPH}/IGU/media").mock(
        return_value=Response(200, json={"id": "c77"})
    )
    out = MetaAdapter(SETTINGS).publish(req("instagram"))
    assert out.status == "pending" and out.state == {"creation_id": "c77"}


@respx.mock
def test_instagram_phase2_finished_publishes():
    respx.get(f"{GRAPH}/c77").mock(
        return_value=Response(200, json={"status_code": "FINISHED"})
    )
    respx.post(f"{GRAPH}/IGU/media_publish").mock(
        return_value=Response(200, json={"id": "ig900"})
    )
    out = MetaAdapter(SETTINGS).publish(req("instagram", state={"creation_id": "c77"}))
    assert out.status == "posted" and out.post_ref == "ig900"


@respx.mock
def test_instagram_phase2_in_progress_stays_pending():
    respx.get(f"{GRAPH}/c77").mock(
        return_value=Response(200, json={"status_code": "IN_PROGRESS"})
    )
    out = MetaAdapter(SETTINGS).publish(req("instagram", state={"creation_id": "c77"}))
    assert out.status == "pending" and out.state == {"creation_id": "c77"}


@respx.mock
def test_expired_token_raises_auth_error():
    respx.post(f"{GRAPH}/PAGE/videos").mock(
        return_value=Response(400, json={"error": {"code": 190, "message": "expired"}})
    )
    with pytest.raises(ChannelAuthError):
        MetaAdapter(SETTINGS).publish(req("facebook"))


@respx.mock
def test_server_error_raises_retryable():
    respx.post(f"{GRAPH}/PAGE/videos").mock(return_value=Response(500, json={}))
    with pytest.raises(ChannelError):
        MetaAdapter(SETTINGS).publish(req("facebook"))
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/channels/meta.py`:

```python
import httpx

from app.channels.base import ChannelAuthError, ChannelError, PublishOutcome, PublishRequest
from app.config import Settings

GRAPH = "https://graph.facebook.com/v21.0"


class MetaAdapter:
    def __init__(self, settings: Settings):
        self.page_id = settings.meta_page_id
        self.ig_user_id = settings.meta_ig_user_id
        self.token = settings.meta_access_token

    def _check(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 500:
            raise ChannelError(f"meta {resp.status_code}")
        data = resp.json()
        if resp.status_code >= 400:
            err = data.get("error", {})
            if err.get("code") == 190:  # invalid/expired token
                raise ChannelAuthError(err.get("message", "token invalid"))
            raise ChannelError(err.get("message", f"meta {resp.status_code}"))
        return data

    def publish(self, req: PublishRequest) -> PublishOutcome:
        if req.channel == "facebook":
            data = self._check(
                httpx.post(
                    f"{GRAPH}/{self.page_id}/videos",
                    data={
                        "file_url": req.media_url,
                        "description": req.body,
                        "access_token": self.token,
                    },
                    timeout=60,
                )
            )
            return PublishOutcome(status="posted", post_ref=data["id"])

        if req.channel == "instagram":
            state = req.state or {}
            if "creation_id" not in state:
                data = self._check(
                    httpx.post(
                        f"{GRAPH}/{self.ig_user_id}/media",
                        data={
                            "media_type": "REELS",
                            "video_url": req.media_url,
                            "caption": req.body,
                            "access_token": self.token,
                        },
                        timeout=60,
                    )
                )
                return PublishOutcome(status="pending", state={"creation_id": data["id"]})

            creation_id = state["creation_id"]
            status = self._check(
                httpx.get(
                    f"{GRAPH}/{creation_id}",
                    params={"fields": "status_code", "access_token": self.token},
                    timeout=30,
                )
            )
            code = status.get("status_code")
            if code == "FINISHED":
                data = self._check(
                    httpx.post(
                        f"{GRAPH}/{self.ig_user_id}/media_publish",
                        data={"creation_id": creation_id, "access_token": self.token},
                        timeout=60,
                    )
                )
                return PublishOutcome(status="posted", post_ref=data["id"])
            if code == "ERROR":
                raise ChannelError("instagram container processing failed")
            return PublishOutcome(status="pending", state=state)

        raise ChannelError(f"MetaAdapter cannot publish channel {req.channel}")
```

- [ ] **Step 3: Run tests** — PASS. **Step 4: Commit** `feat: Meta adapter (FB page video, IG Reels two-phase)`

---

### Task 11: XAdapter (text + UTM link post)

**Files:**
- Create: `backend/app/channels/x.py`
- Test: `backend/tests/test_x_adapter.py`

**Interfaces:**
- Implements `ChannelAdapter`. **Deliberate Phase 1 cut:** posts text + UTM link only (no native video upload — X is the lowest-priority channel; native media joins in Phase 2 with the other media-heavy work). OAuth 1.0a user-context signing via authlib.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_x_adapter.py`:

```python
import pytest
import respx
from httpx import Response

from app.channels.base import ChannelAuthError, ChannelError, PublishRequest
from app.channels.x import TWEETS_URL, XAdapter
from app.config import Settings

SETTINGS = Settings(
    x_consumer_key="ck", x_consumer_secret="cs",
    x_access_token="at", x_access_token_secret="ats",
)


def req(body="ข้อความ https://eduverse.one?utm_source=x") -> PublishRequest:
    return PublishRequest(
        item_id="i1", channel="x", title=None, body=body, media_url=None, state=None
    )


@respx.mock
def test_posts_tweet_with_oauth1_header():
    route = respx.post(TWEETS_URL).mock(
        return_value=Response(201, json={"data": {"id": "190001"}})
    )
    out = XAdapter(SETTINGS).publish(req())
    assert out.status == "posted" and out.post_ref == "190001"
    assert route.calls[0].request.headers["Authorization"].startswith("OAuth ")


@respx.mock
def test_truncates_over_280_chars_preserving_link():
    long_body = ("ก" * 300) + "\n\nhttps://eduverse.one?utm_source=x"
    route = respx.post(TWEETS_URL).mock(
        return_value=Response(201, json={"data": {"id": "1"}})
    )
    XAdapter(SETTINGS).publish(req(long_body))
    import json
    text = json.loads(route.calls[0].request.read())["text"]
    assert len(text) <= 280
    assert "https://eduverse.one" in text


@respx.mock
def test_401_raises_auth_error():
    respx.post(TWEETS_URL).mock(return_value=Response(401, json={}))
    with pytest.raises(ChannelAuthError):
        XAdapter(SETTINGS).publish(req())


@respx.mock
def test_5xx_raises_retryable():
    respx.post(TWEETS_URL).mock(return_value=Response(503, json={}))
    with pytest.raises(ChannelError):
        XAdapter(SETTINGS).publish(req())
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/channels/x.py`:

```python
import httpx
from authlib.oauth1 import ClientAuth

from app.channels.base import ChannelAuthError, ChannelError, PublishOutcome, PublishRequest
from app.config import Settings

TWEETS_URL = "https://api.x.com/2/tweets"
LIMIT = 280


def _fit(body: str) -> str:
    if len(body) <= LIMIT:
        return body
    lines = body.split("\n\n")
    link = lines[-1] if lines and lines[-1].startswith("http") else ""
    room = LIMIT - (len(link) + 2 if link else 0) - 1
    head = body[: max(room, 0)].rstrip()
    return f"{head}…\n\n{link}" if link else f"{head}…"


class XAdapter:
    def __init__(self, settings: Settings):
        self.auth = ClientAuth(
            client_id=settings.x_consumer_key,
            client_secret=settings.x_consumer_secret,
            token=settings.x_access_token,
            token_secret=settings.x_access_token_secret,
        )

    def publish(self, req: PublishRequest) -> PublishOutcome:
        url, headers, payload = self.auth.prepare("POST", TWEETS_URL, {}, b"")
        resp = httpx.post(
            url, headers=dict(headers), json={"text": _fit(req.body)}, timeout=30
        )
        if resp.status_code in (401, 403):
            raise ChannelAuthError(f"x auth {resp.status_code}")
        if resp.status_code >= 500 or resp.status_code == 429:
            raise ChannelError(f"x {resp.status_code}")
        if resp.status_code >= 400:
            raise ChannelError(f"x {resp.status_code}: {resp.text[:200]}")
        return PublishOutcome(status="posted", post_ref=resp.json()["data"]["id"])
```

Note for the implementer: `authlib.oauth1.ClientAuth.prepare(method, uri, headers, body)` returns `(uri, headers, body)` with the signed `Authorization` header. If the installed authlib version exposes a different signature, adapt inside this file only — the test asserting an `OAuth `-prefixed header is the contract.

- [ ] **Step 3: Run tests** — PASS. **Step 4: Commit** `feat: X adapter (OAuth1 text+link post, 280-char fitting)`

---

### Task 12: LineAdapter (broadcast)

**Files:**
- Create: `backend/app/channels/line.py`
- Test: `backend/tests/test_line_adapter.py`

**Interfaces:**
- Implements `ChannelAdapter`. Broadcast text message (body already contains UTM link). `post_ref` = `x-line-request-id` response header.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_line_adapter.py`:

```python
import pytest
import respx
from httpx import Response

from app.channels.base import ChannelAuthError, ChannelError, PublishRequest
from app.channels.line import BROADCAST_URL, LineAdapter
from app.config import Settings

SETTINGS = Settings(line_channel_access_token="LTOK")


def req() -> PublishRequest:
    return PublishRequest(
        item_id="i1", channel="line", title=None,
        body="คอร์สใหม่ https://eduverse.one?utm_source=line", media_url=None, state=None,
    )


@respx.mock
def test_broadcast_success():
    route = respx.post(BROADCAST_URL).mock(
        return_value=Response(200, json={}, headers={"x-line-request-id": "rid-1"})
    )
    out = LineAdapter(SETTINGS).publish(req())
    assert out.status == "posted" and out.post_ref == "rid-1"
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer LTOK"
    assert "คอร์สใหม่".encode() in sent.read()


@respx.mock
def test_401_auth_error():
    respx.post(BROADCAST_URL).mock(return_value=Response(401, json={}))
    with pytest.raises(ChannelAuthError):
        LineAdapter(SETTINGS).publish(req())


@respx.mock
def test_429_retryable():
    respx.post(BROADCAST_URL).mock(return_value=Response(429, json={}))
    with pytest.raises(ChannelError):
        LineAdapter(SETTINGS).publish(req())
```

- [ ] **Step 2: Run FAIL, implement**

`backend/app/channels/line.py`:

```python
import httpx

from app.channels.base import ChannelAuthError, ChannelError, PublishOutcome, PublishRequest
from app.config import Settings

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"


class LineAdapter:
    def __init__(self, settings: Settings):
        self.token = settings.line_channel_access_token

    def publish(self, req: PublishRequest) -> PublishOutcome:
        resp = httpx.post(
            BROADCAST_URL,
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messages": [{"type": "text", "text": req.body[:4900]}]},
            timeout=30,
        )
        if resp.status_code == 401:
            raise ChannelAuthError("line token invalid")
        if resp.status_code >= 400:
            raise ChannelError(f"line {resp.status_code}: {resp.text[:200]}")
        return PublishOutcome(
            status="posted", post_ref=resp.headers.get("x-line-request-id", "line-ok")
        )
```

- [ ] **Step 3: Run tests + full suite** — `pytest -q` — all PASS
- [ ] **Step 4: Commit** `feat: LINE OA broadcast adapter`

---

### Task 13: Frontend — review queue

**Files:**
- Create: `frontend/` via `npx create-next-app@latest frontend --ts --app --tailwind --no-eslint --src-dir=false --import-alias "@/*"`
- Create: `frontend/lib/api.ts`, `frontend/app/login/page.tsx`, `frontend/app/page.tsx`, `frontend/app/new/page.tsx`, `frontend/components/ItemCard.tsx`
- Test: `frontend/lib/api.test.ts` (vitest)

**Interfaces:**
- Consumes: the Task 7 REST API. Backend URL from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`); admin token kept in `localStorage["am_token"]`.

- [ ] **Step 1: Scaffold** — run the create-next-app command above; add `vitest` (`npm i -D vitest`) and `"test": "vitest run"` script.

- [ ] **Step 2: Write the failing test**

`frontend/lib/api.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api";

describe("apiFetch", () => {
  it("sends bearer token and parses json", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("localStorage", {
      getItem: () => "tok123",
    } as unknown as Storage);

    const data = await apiFetch("/api/items");
    expect(data).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/items");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok123");
  });

  it("throws on non-2xx with body text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 422 })));
    vi.stubGlobal("localStorage", { getItem: () => "t" } as unknown as Storage);
    await expect(apiFetch("/api/items")).rejects.toThrow("nope");
  });
});
```

Run: `npm test` — Expected: FAIL (module missing)

- [ ] **Step 3: Implement `frontend/lib/api.ts`**

```typescript
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function apiFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const token = localStorage.getItem("am_token") ?? "";
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...((init.headers as Record<string, string>) ?? {}),
  };
  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}
```

Run: `npm test` — PASS. Commit: `feat: frontend scaffold + api client`

- [ ] **Step 4: Login page** — `frontend/app/login/page.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Login() {
  const [token, setToken] = useState("");
  const router = useRouter();
  return (
    <main className="mx-auto mt-24 max-w-sm space-y-4 p-4">
      <h1 className="text-xl font-bold">AutoMarketing</h1>
      <input
        className="w-full rounded border p-2"
        type="password"
        placeholder="Admin token"
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      <button
        className="w-full rounded bg-black p-2 text-white"
        onClick={() => {
          localStorage.setItem("am_token", token);
          router.push("/");
        }}
      >
        เข้าสู่ระบบ
      </button>
    </main>
  );
}
```

- [ ] **Step 5: Item card** — `frontend/components/ItemCard.tsx`:

```tsx
"use client";
import { useState } from "react";
import { apiFetch } from "@/lib/api";

type Caption = {
  channel: string; title: string | null; body: string;
  hashtags: string[]; edited_by_human: boolean;
};
type Publication = {
  channel: string; status: string; scheduled_at: string | null;
  posted_at: string | null; post_ref: string | null;
  attempts: number; last_error: string | null;
};
export type Item = {
  id: string; slug: string; topic: string; status: string;
  media_url: string | null; banned_violations: string[];
  reject_reason: string | null; captions: Caption[]; publications: Publication[];
};

const CHANNELS = ["tiktok", "youtube", "instagram", "facebook", "x", "line"];

export default function ItemCard({ item, onChanged }: { item: Item; onChanged: () => void }) {
  const [captions, setCaptions] = useState<Caption[]>(item.captions);
  const [when, setWhen] = useState("");
  const [channels, setChannels] = useState<string[]>(["facebook", "instagram", "x", "line"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await fn(); onChanged(); } catch (e) { setError(String(e)); }
    setBusy(false);
  };

  const saveCaption = (c: Caption) =>
    act(() => apiFetch(`/api/items/${item.id}/captions`, { method: "PUT", body: JSON.stringify(c) }));

  return (
    <div className="space-y-3 rounded-xl border p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{item.topic}</h2>
        <span className="rounded bg-gray-100 px-2 py-1 text-xs">{item.status}</span>
      </div>
      {item.media_url && (
        <video src={item.media_url} controls className="max-h-80 w-full rounded bg-black" />
      )}
      {item.banned_violations.length > 0 && (
        <p className="text-sm text-red-600">คำต้องห้าม: {item.banned_violations.join(", ")}</p>
      )}
      {captions.map((c) => (
        <div key={c.channel} className="space-y-1">
          <label className="text-xs font-semibold uppercase">{c.channel}</label>
          <textarea
            className="w-full rounded border p-2 text-sm"
            rows={3}
            value={c.body}
            onChange={(e) =>
              setCaptions(captions.map((x) => (x.channel === c.channel ? { ...x, body: e.target.value } : x)))
            }
            onBlur={() => saveCaption(captions.find((x) => x.channel === c.channel)!)}
          />
        </div>
      ))}
      {item.status === "in_review" && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {CHANNELS.map((ch) => (
              <label key={ch} className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={channels.includes(ch)}
                  onChange={(e) =>
                    setChannels(e.target.checked ? [...channels, ch] : channels.filter((x) => x !== ch))
                  }
                />
                {ch}
              </label>
            ))}
          </div>
          <input
            type="datetime-local"
            className="rounded border p-2 text-sm"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              disabled={busy || !when}
              className="rounded bg-green-600 px-3 py-2 text-sm text-white disabled:opacity-40"
              onClick={() =>
                act(() =>
                  apiFetch(`/api/items/${item.id}/approve`, {
                    method: "POST",
                    body: JSON.stringify({
                      scheduled_at: new Date(when).toISOString(),
                      channels,
                    }),
                  })
                )
              }
            >
              อนุมัติ + ตั้งเวลา
            </button>
            <button
              disabled={busy}
              className="rounded bg-red-600 px-3 py-2 text-sm text-white disabled:opacity-40"
              onClick={() =>
                act(() =>
                  apiFetch(`/api/items/${item.id}/reject`, {
                    method: "POST",
                    body: JSON.stringify({ reason: "rejected in review" }),
                  })
                )
              }
            >
              ปฏิเสธ
            </button>
          </div>
        </div>
      )}
      {item.status === "failed" && (
        <button
          disabled={busy}
          className="rounded bg-amber-600 px-3 py-2 text-sm text-white"
          onClick={() => act(() => apiFetch(`/api/items/${item.id}/retry`, { method: "POST" }))}
        >
          ลองใหม่
        </button>
      )}
      {item.publications.length > 0 && (
        <table className="w-full text-xs">
          <tbody>
            {item.publications.map((p) => (
              <tr key={p.channel} className="border-t">
                <td className="py-1 font-medium">{p.channel}</td>
                <td>{p.status}</td>
                <td className="text-red-600">{p.last_error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 6: Queue page** — `frontend/app/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ItemCard, { Item } from "@/components/ItemCard";
import { apiFetch } from "@/lib/api";

const TABS = ["in_review", "scheduled", "posted", "failed", "rejected", "idea"];

export default function Queue() {
  const [tab, setTab] = useState("in_review");
  const [items, setItems] = useState<Item[]>([]);
  const load = useCallback(async () => {
    try {
      setItems((await apiFetch(`/api/items?status=${tab}`)) as Item[]);
    } catch {
      window.location.href = "/login";
    }
  }, [tab]);
  useEffect(() => { load(); }, [load]);

  return (
    <main className="mx-auto max-w-2xl space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Review Queue</h1>
        <Link href="/new" className="rounded bg-black px-3 py-2 text-sm text-white">
          + คอนเทนต์ใหม่
        </Link>
      </div>
      <div className="flex gap-2 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded px-3 py-1 text-sm ${tab === t ? "bg-black text-white" : "bg-gray-100"}`}
          >
            {t}
          </button>
        ))}
      </div>
      {items.map((i) => (
        <ItemCard key={i.id} item={i} onChanged={load} />
      ))}
      {items.length === 0 && <p className="text-sm text-gray-500">ไม่มีรายการ</p>}
    </main>
  );
}
```

- [ ] **Step 7: New item page** — `frontend/app/new/page.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";

export default function NewItem() {
  const [topic, setTopic] = useState("");
  const [hook, setHook] = useState("");
  const [link, setLink] = useState("https://eduverse.one");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  const submit = async () => {
    setBusy(true); setError("");
    const form = new FormData();
    form.set("topic", topic);
    if (hook) form.set("hook", hook);
    if (link) form.set("link", link);
    if (file) form.set("file", file);
    try {
      await apiFetch("/api/items", { method: "POST", body: form });
      router.push("/");
    } catch (e) {
      setError(String(e));
    }
    setBusy(false);
  };

  return (
    <main className="mx-auto max-w-md space-y-3 p-4">
      <h1 className="text-xl font-bold">คอนเทนต์ใหม่</h1>
      <input className="w-full rounded border p-2" placeholder="หัวข้อ"
        value={topic} onChange={(e) => setTopic(e.target.value)} />
      <input className="w-full rounded border p-2" placeholder="Hook (ไม่บังคับ)"
        value={hook} onChange={(e) => setHook(e.target.value)} />
      <input className="w-full rounded border p-2" placeholder="ลิงก์"
        value={link} onChange={(e) => setLink(e.target.value)} />
      <input type="file" accept="video/mp4" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <button
        disabled={busy || !topic}
        className="w-full rounded bg-black p-2 text-white disabled:opacity-40"
        onClick={submit}
      >
        {busy ? "กำลังเขียนแคปชัน..." : "สร้าง + เขียนแคปชัน"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </main>
  );
}
```

- [ ] **Step 8: Verify build + manual smoke**

Run: `cd frontend && npm run build` — Expected: clean build.
Manual smoke (backend running with `ENABLED_CHANNELS=dryrun`): login → create item with a small mp4 → captions appear → edit one → approve for `dryrun` scheduled 1 minute out → `curl -X POST localhost:8000/internal/tick -H 'X-Tick-Token: dev-tick-token'` → item shows `posted`; `media/dryrun_feed.jsonl` contains the body with `utm_source=dryrun`.

- [ ] **Step 9: Commit** `feat: review queue frontend (login, queue tabs, item card, new item)`

---

### Task 14: Platform setup docs + audit applications (human-in-the-loop)

**Files:**
- Create: `docs/PLATFORM_SETUP.md`
- Modify: `.env.example` (cross-reference doc)

**Interfaces:** none (documentation + founder checklist). This task is complete when the doc exists and the founder has the checklist; actually obtaining tokens can proceed in parallel with deployment.

- [ ] **Step 1: Write `docs/PLATFORM_SETUP.md`** with these sections (each a numbered founder checklist ending in "which env var to fill"):

1. **Meta (Facebook Page + Instagram)** — create app at developers.facebook.com (Business type); add Facebook Login + Instagram Graph products; keep app in Dev Mode (posting to your own Page/IG works without App Review); link IG business account to the Page; generate long-lived Page access token via Graph API Explorer (`pages_manage_posts`, `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`); fill `META_PAGE_ID`, `META_IG_USER_ID`, `META_ACCESS_TOKEN`.
2. **X** — developer.x.com free tier; create project+app; enable OAuth 1.0a user context with Read/Write; generate consumer keys + access token/secret for the brand account; fill the four `X_*` vars.
3. **YouTube (audit application — file now, adapter lands Phase 2)** — Google Cloud project; enable YouTube Data API v3; OAuth consent screen (External) + request `youtube.upload` scope verification/audit; note: until audit clears, API uploads are locked private — that is our planned Phase 2 behavior.
4. **TikTok (audit application — file now, adapter lands Phase 2)** — developers.tiktok.com; register app; apply for Content Posting API; note unaudited apps can only push drafts to your own inbox — our planned interim behavior.
5. **LINE OA** — reuse the existing Eduverse LINE OA channel access token; get the founder's LINE user ID (from the existing support-bot webhook logs) for failure alerts; fill `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_FOUNDER_USER_ID`; check broadcast quota for the current plan and note it in the doc.

- [ ] **Step 2: Commit** `docs: platform setup + audit application checklist`

---

### Task 15: Deploy to Cloud Run

**Files:**
- Create: `backend/Dockerfile`, `frontend/Dockerfile`, `cloudbuild.yaml`

**Interfaces:** none new; deployment of Tasks 0–13 as built.

- [ ] **Step 1: Write Dockerfiles**

`backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY ../strategy.yaml ./strategy.yaml
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

(If the Docker build context forbids `../strategy.yaml`, move `strategy.yaml` into `backend/` and set `STRATEGY_PATH` accordingly — decide at build time, both are supported by config.)

`frontend/Dockerfile`: standard Next.js standalone build (`next.config.ts` with `output: "standalone"`), `node:20-slim`, `CMD ["node", "server.js"]`, port 8080.

- [ ] **Step 2: Deploy using the existing deploy skill**

At execution time invoke the `deploy-fastapi-nextjs-cloud-run` skill (it encodes this GCP org's constraints — no public buckets, service-account grants, post-deploy verification of both services). Backend env: `MEDIA_BACKEND=gcs`, `GCS_BUCKET`, `DATABASE_URL` (Cloud SQL), `ENABLED_CHANNELS`, tokens from Secret Manager. Run Alembic migration against Cloud SQL before first request.

- [ ] **Step 3: Create the Cloud Scheduler tick**

```bash
gcloud scheduler jobs create http automarketing-tick \
  --schedule="*/5 * * * *" \
  --uri="https://<backend-url>/internal/tick" \
  --http-method=POST \
  --headers="X-Tick-Token=<TICK_TOKEN>" \
  --location=asia-southeast1
```

- [ ] **Step 4: Verify in production**

- `GET /healthz` → 200 on backend URL; frontend loads and logs in.
- Create a real item with a tiny mp4, approve for `dryrun`, wait ≤5 min, confirm `posted` (proves scheduler + DB + media path in prod).
- Then flip `ENABLED_CHANNELS=facebook,instagram,x,line,dryrun` once tokens are in Secret Manager, and make one real scheduled post to each configured channel.

- [ ] **Step 5: Commit** `chore: dockerfiles + cloudbuild for Cloud Run deploy`

---

## Self-review notes

- **Spec coverage (Phase 1):** scaffold (T0), DB/state machine (T1–2), UTM (T3), banned gate (T4), media upload/serving (T5), caption writer all 6 channels (T6), items API + review actions (T7), adapter contract + DryRun (T8), publisher with idempotent row-level publishing, retries, pending-external, auth pausing, LINE alerts, tick endpoint (T9), Meta/X/LINE adapters (T10–12), review queue UI (T13), audit applications + platform setup (T14), deploy + scheduler (T15). Spec's Phase 1 line "manual video upload" = T5+T7; "file TikTok + YouTube audit applications" = T14 items 3–4.
- **Deliberate cuts (stated, not silent):** X posts text+link only (native X video → Phase 2); LINE broadcast is text+link (video message needs a preview image → Phase 2); no idempotency table beyond the publication row itself (the row is the idempotency unit; `SKIP LOCKED` prevents double-send between concurrent ticks).
- **Type consistency check:** `PublishRequest`/`PublishOutcome` fields identical across T8–T12 and the publisher; `item_json` keys match what `ItemCard`/`Queue` read; caption channels list identical in T6 schema, T7 `CHANNELS`, and T13 `CHANNELS`.
