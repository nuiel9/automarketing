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
