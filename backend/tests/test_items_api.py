from datetime import datetime, timedelta, timezone

import pytest

import app.api.items as items_api
from app.config import get_settings
from app.strategy import Strategy
from tests.test_captions import FAKE

AUTH = {"Authorization": "Bearer dev-admin-token"}
STRATEGY = Strategy(voice="v", audiences=["a"], banned_words=["ห้ามคำนี้"], platform_notes={})


@pytest.fixture(autouse=True)
def patch_deps(monkeypatch):
    monkeypatch.setattr(items_api, "write_captions", lambda topic, hook, strategy: FAKE)
    monkeypatch.setattr(items_api, "load_strategy", lambda path: STRATEGY)
    # Existing tests approve with facebook/instagram/x/line/dryrun; the approve
    # endpoint now rejects any channel not in Settings.channels(), so those
    # channels must actually be enabled here rather than relying on the
    # "dryrun"-only default.
    monkeypatch.setattr(
        get_settings(), "enabled_channels", "facebook,instagram,x,line,dryrun"
    )


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


def test_approve_rejects_empty_channels(client_with_db):
    item = _create(client_with_db).json()
    when = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/approve",
        json={"scheduled_at": when, "channels": []},
        headers=AUTH,
    )
    assert resp.status_code == 422
    assert "channels" in resp.text
    get_resp = client_with_db.get(f"/api/items/{item['id']}", headers=AUTH)
    assert get_resp.json()["status"] == "in_review"


def test_approve_rejects_not_enabled_channel(client_with_db):
    item = _create(client_with_db).json()
    when = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/approve",
        json={"scheduled_at": when, "channels": ["tiktok"]},
        headers=AUTH,
    )
    assert resp.status_code == 422
    assert "tiktok" in resp.text
    get_resp = client_with_db.get(f"/api/items/{item['id']}", headers=AUTH)
    assert get_resp.json()["status"] == "in_review"


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


def _approve(client, item_id, channels=("facebook",)):
    when = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    return client.post(
        f"/api/items/{item_id}/approve",
        json={"scheduled_at": when, "channels": list(channels)},
        headers=AUTH,
    )


def test_edit_caption_locked_after_approval(client_with_db):
    item = _create(client_with_db).json()
    original_body = next(c["body"] for c in item["captions"] if c["channel"] == "facebook")
    approve_resp = _approve(client_with_db, item["id"])
    assert approve_resp.status_code == 200

    resp = client_with_db.put(
        f"/api/items/{item['id']}/captions",
        json={"channel": "facebook", "title": None, "body": "แก้หลังอนุมัติ", "hashtags": []},
        headers=AUTH,
    )
    assert resp.status_code == 409
    assert "locked" in resp.text

    get_resp = client_with_db.get(f"/api/items/{item['id']}", headers=AUTH)
    body = next(c["body"] for c in get_resp.json()["captions"] if c["channel"] == "facebook")
    assert body == original_body


def test_regenerate_captions_locked_after_approval(client_with_db):
    item = _create(client_with_db).json()
    approve_resp = _approve(client_with_db, item["id"])
    assert approve_resp.status_code == 200

    resp = client_with_db.post(f"/api/items/{item['id']}/captions", headers=AUTH)
    assert resp.status_code == 409
    assert "locked" in resp.text


def test_edit_caption_allowed_while_in_review(client_with_db):
    item = _create(client_with_db).json()
    resp = client_with_db.put(
        f"/api/items/{item['id']}/captions",
        json={"channel": "facebook", "title": None, "body": "แก้ระหว่างรีวิว", "hashtags": []},
        headers=AUTH,
    )
    assert resp.status_code == 200
    body = next(c["body"] for c in resp.json()["captions"] if c["channel"] == "facebook")
    assert body == "แก้ระหว่างรีวิว"


def test_retry_resets_failed_publications_and_clears_external_state(client_with_db, db):
    from app.models import ContentItem

    item = _create(client_with_db).json()
    approve_resp = _approve(client_with_db, item["id"])
    assert approve_resp.status_code == 200

    db_item = db.get(ContentItem, item["id"])
    db_item.status = "failed"
    pub = db_item.publications[0]
    pub.status = "failed"
    pub.attempts = 3
    pub.last_error = "boom"
    pub.external_state = {"creation_id": "c9"}
    db.commit()

    resp = client_with_db.post(f"/api/items/{item['id']}/retry", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "scheduled"
    pub_body = body["publications"][0]
    assert pub_body["status"] == "pending"
    assert pub_body["attempts"] == 0
    assert pub_body["last_error"] is None

    db.refresh(pub)
    assert pub.external_state is None


def test_approve_normalizes_naive_scheduled_at_to_utc(client_with_db):
    item = _create(client_with_db).json()
    naive = "2026-08-06T12:00:00"  # no tzinfo
    resp = client_with_db.post(
        f"/api/items/{item['id']}/approve",
        json={"scheduled_at": naive, "channels": ["facebook"]},
        headers=AUTH,
    )
    assert resp.status_code == 200
    scheduled_at = resp.json()["publications"][0]["scheduled_at"]
    assert scheduled_at.endswith("+00:00")
    assert datetime.fromisoformat(scheduled_at) == datetime(
        2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc
    )
