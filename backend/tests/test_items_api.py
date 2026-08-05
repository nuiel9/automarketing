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
