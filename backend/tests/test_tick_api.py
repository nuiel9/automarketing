from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_session
from app.main import create_app
from app.models import Base, Caption, ContentItem, Publication, utcnow


def test_tick_requires_token_missing_header(client_with_db):
    resp = client_with_db.post("/internal/tick")
    assert resp.status_code == 401


def test_tick_requires_token_wrong_value(client_with_db):
    resp = client_with_db.post("/internal/tick", headers={"X-Tick-Token": "wrong"})
    assert resp.status_code == 401


def test_tick_happy_path_persists_across_sessions(tmp_path, monkeypatch):
    # client_with_db's get_session override (`lambda: (yield db)`) never
    # commits, so a happy-path test built on it can pass even if the real
    # request path never persisted anything -- it would just be reading back
    # in-memory ORM state on the same session. To actually prove durability,
    # this test wires a get_session override that MIRRORS app/db.py's
    # production generator (commit-after-yield, on a file-backed sqlite
    # engine so a brand-new session can independently re-read it), then
    # asserts through that brand-new session rather than the seeded one.
    #
    # Caveat: this is a hand-written mirror of app/db.py's get_session, not
    # a call-through to it -- app.db.get_session is never exercised here (it
    # still targets the Postgres URL from settings, which isn't available in
    # tests). A regression that deleted `session.commit()` from the actual
    # app/db.py would NOT be caught by this test; it would only be caught if
    # this test's own override lost its commit, which the sanity-check below
    # (and repeated manually for this round) confirms it does detect.
    monkeypatch.setattr(get_settings(), "media_root", str(tmp_path))

    engine = create_engine(f"sqlite:///{tmp_path / 'tick.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_session():
        with session_factory() as s:
            yield s
            s.commit()

    with session_factory() as seed_session:
        item = ContentItem(
            slug="w32-founder-clip-t", topic="t", status="scheduled",
            link="https://eduverse.one",
        )
        item.captions.append(Caption(channel="dryrun", body="hello", hashtags=["#a"]))
        pub = Publication(channel="dryrun", scheduled_at=utcnow() - timedelta(minutes=1))
        item.publications.append(pub)
        seed_session.add(item)
        seed_session.commit()
        pub_id = pub.id

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)

    resp = client.post(
        "/internal/tick", headers={"X-Tick-Token": get_settings().tick_token}
    )
    assert resp.status_code == 200
    assert resp.json()["posted"] == 1

    with session_factory() as fresh_session:
        row = fresh_session.get(Publication, pub_id)
        assert row.status == "posted"
        assert row.post_ref is not None
        assert row.item.status == "posted"
