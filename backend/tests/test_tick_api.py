from datetime import timedelta

from app.config import get_settings
from app.models import Caption, ContentItem, Publication, utcnow


def test_tick_requires_token_missing_header(client_with_db):
    resp = client_with_db.post("/internal/tick")
    assert resp.status_code == 401


def test_tick_requires_token_wrong_value(client_with_db):
    resp = client_with_db.post("/internal/tick", headers={"X-Tick-Token": "wrong"})
    assert resp.status_code == 401


def test_tick_happy_path_posts_due_publication(client_with_db, db, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_root", str(tmp_path))

    item = ContentItem(
        slug="w32-founder-clip-t", topic="t", status="scheduled",
        link="https://eduverse.one",
    )
    item.captions.append(Caption(channel="dryrun", body="hello", hashtags=["#a"]))
    pub = Publication(channel="dryrun", scheduled_at=utcnow() - timedelta(minutes=1))
    item.publications.append(pub)
    db.add(item)
    db.commit()

    resp = client_with_db.post(
        "/internal/tick", headers={"X-Tick-Token": get_settings().tick_token}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["posted"] == 1

    assert pub.status == "posted"
    assert item.status == "posted"
