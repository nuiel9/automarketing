from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.items as items_api
from app.db import get_session
from app.main import create_app
from app.models import Base, ContentItem
from tests.test_items_api import AUTH, _create, patch_deps  # noqa: F401 -- reuse Phase 1 helpers
# patch_deps is autouse in test_items_api.py, but pytest only auto-applies an
# autouse fixture to tests in modules where it's a bound name -- importing it
# here (rather than just AUTH/_create) is what makes it run for this module's
# tests too, mocking write_captions/load_strategy so _create() below doesn't
# hit the real filesystem/Gemini API.


@pytest.fixture(autouse=True)
def fake_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(items_api, "get_dispatcher",
                        lambda s: type("D", (), {"dispatch": lambda self, i: calls.append(i)})())
    return calls


@pytest.fixture(autouse=True)
def scenario_root(monkeypatch):
    # items_api.SCENARIO_ROOT is `os.environ.get("SCENARIO_ROOT", "./scenarios")`
    # read once at import time, so it's captured relative to whatever cwd the
    # test process started in (backend/, per the run instructions) -- setting
    # an env var here would be too late. Point the module attribute directly
    # at the real tracked fixture (repo root scenarios/fixture-demo.yaml)
    # rather than writing a duplicate YAML into tmp_path, so
    # test_unknown_scenario_is_422 stays meaningful: the root exists, the
    # requested scenario genuinely doesn't.
    monkeypatch.setattr(
        items_api, "SCENARIO_ROOT", str(Path(__file__).resolve().parents[2] / "scenarios")
    )


def test_render_moves_item_to_rendering_and_dispatches(client_with_db, db, fake_dispatch):
    # Deliberately not _create(): that helper uploads a file and always runs
    # _generate(), which transitions idea -> in_review on caption success --
    # so a _create()d item is never a fresh "idea"/no-media item (state.py
    # allows idea -> rendering, failed -> rendering, and now in_review ->
    # rendering too -- see test_render_from_in_review_item_succeeds below
    # for that path; Task 10's render control gates on !media_url rather
    # than status). Construct the item directly in "idea", same pattern as
    # test_render_from_posted_item_is_409 below.
    from app.models import ContentItem
    item = ContentItem(slug="w32-video-x", topic="t", status="idea")
    db.add(item); db.commit()
    resp = client_with_db.post(
        f"/api/items/{item.id}/render",
        json={"format": "demo", "scenario": "fixture-demo"}, headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rendering"
    assert body["scenario"] == "fixture-demo"
    assert fake_dispatch == [item.id]


def test_render_from_in_review_item_succeeds(client_with_db, fake_dispatch):
    # _create() always ends with the item in_review (captions generate
    # successfully, per patch_deps). An item that's been reviewed but has
    # no video yet must still be renderable -- the render control isn't
    # gated on review status, only on whether media exists.
    item = _create(client_with_db).json()
    assert item["status"] == "in_review"
    resp = client_with_db.post(
        f"/api/items/{item['id']}/render",
        json={"format": "tips"}, headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rendering"
    assert fake_dispatch == [item["id"]]


def test_render_switching_away_from_motion_ad_clears_the_stale_job_id(client_with_db, db, fake_dispatch):
    # A stale aivdo_job_id from a previous motion_ad lifetime must not
    # survive a switch to another format -- otherwise switching this item
    # back to motion_ad later would try to resume a job that has nothing to
    # do with this render attempt.
    from app.models import ContentItem
    item = ContentItem(slug="w32-switch", topic="t", status="failed",
                       format="motion_ad", aivdo_job_id="job-old")
    db.add(item); db.commit()

    resp = client_with_db.post(
        f"/api/items/{item.id}/render", json={"format": "tips"}, headers=AUTH
    )

    assert resp.status_code == 200
    db.refresh(item)
    assert item.aivdo_job_id is None


def test_render_switching_away_from_motion_ad_reports_the_job_it_orphans(
    client_with_db, db, fake_dispatch, monkeypatch
):
    # Clearing the id is correct (see the test above) -- but it is only still
    # set here because worker.py never confirmed the job dead, which means
    # AIVDO may still be holding a live job whose 5 credits are already spent.
    # Those credits are unrecoverable: AIVDO refunds only when *dispatch*
    # fails, and its sweep_stalled_jobs selects status == "running", so a job
    # that died before that write sits at "queued" forever. Dropping the id
    # silently makes a paid job both unrecoverable and invisible; the operator
    # has to be told, because nothing else will ever mention it again.
    notes = []
    monkeypatch.setattr(items_api, "line_notify", notes.append)
    item = ContentItem(slug="w33-orphan", topic="t", status="failed",
                       format="motion_ad", aivdo_job_id="job-paid")
    db.add(item); db.commit()

    resp = client_with_db.post(
        f"/api/items/{item.id}/render", json={"format": "tips"}, headers=AUTH
    )

    assert resp.status_code == 200
    # The id itself must be in the alert -- it is the only handle anyone has
    # for asking AIVDO what happened to those credits.
    assert any("job-paid" in n for n in notes), notes


def test_render_format_switch_is_silent_when_no_job_was_paid_for(
    client_with_db, db, fake_dispatch, monkeypatch
):
    # The common case is switching format on an item that never rendered a
    # motion_ad. Alerting there would train the founder to ignore the alert
    # that matters.
    notes = []
    monkeypatch.setattr(items_api, "line_notify", notes.append)
    item = ContentItem(slug="w33-no-job", topic="t", status="failed",
                       format="demo", aivdo_job_id=None)
    db.add(item); db.commit()

    resp = client_with_db.post(
        f"/api/items/{item.id}/render", json={"format": "tips"}, headers=AUTH
    )

    assert resp.status_code == 200
    assert notes == []


def test_render_motion_ad_again_leaves_an_existing_job_id_alone(client_with_db, db, fake_dispatch):
    # Re-requesting motion_ad on an item that still has a job id must not
    # clear it here -- worker.py's resume-instead-of-recharge logic depends
    # on it still being there when the render actually runs.
    from app.models import ContentItem
    item = ContentItem(slug="w32-same-format", topic="t", status="failed",
                       format="motion_ad", aivdo_job_id="job-existing")
    db.add(item); db.commit()

    resp = client_with_db.post(
        f"/api/items/{item.id}/render", json={"format": "motion_ad"}, headers=AUTH
    )

    assert resp.status_code == 200
    db.refresh(item)
    assert item.aivdo_job_id == "job-existing"


def test_bad_format_is_422(client_with_db):
    item = _create(client_with_db).json()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/render", json={"format": "founder_clip"}, headers=AUTH
    )
    assert resp.status_code == 422


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


def test_dispatch_failure_marks_item_failed_and_notifies(client_with_db, db, monkeypatch):
    from app.models import ContentItem
    item = ContentItem(slug="w32-video-z", topic="t", status="idea")
    db.add(item); db.commit()

    class BoomDispatcher:
        def dispatch(self, item_id):
            raise RuntimeError("cloud run unavailable")

    monkeypatch.setattr(items_api, "get_dispatcher", lambda s: BoomDispatcher())
    notes = []
    monkeypatch.setattr(items_api, "line_notify", notes.append)

    resp = client_with_db.post(
        f"/api/items/{item.id}/render", json={"format": "tips"}, headers=AUTH
    )
    assert resp.status_code == 502

    # This assertion is NOT load-bearing for durability -- see the
    # file-backed-session tests below for why, and for the check that
    # actually is. client_with_db's get_session override (`lambda: (yield
    # db)`) hands out the SAME session object for every request in this
    # test, and never commits it. So this GET reads the mutated ContentItem
    # straight out of that session's identity map, in-transaction -- it
    # would pass identically whether the except block below called
    # session.commit() or session.flush(). It's kept because it still
    # proves the response *contract* (status code, body shape), just not
    # persistence.
    got = client_with_db.get(f"/api/items/{item.id}", headers=AUTH).json()
    assert got["status"] == "failed"
    assert got["render_error"] and "cloud run unavailable" in got["render_error"]
    assert notes


def _durable_client(tmp_path, db_name):
    # Mirrors app/db.py's production get_session generator (commit-after-
    # yield) on a file-backed sqlite engine -- unlike client_with_db (a
    # single shared, never-committed session), each request here opens its
    # own session against a real file, so only a `session.commit()` in the
    # handler makes a write visible to a DIFFERENT session opened later.
    # Same pattern as test_tick_api.py::test_tick_happy_path_persists_across_sessions.
    engine = create_engine(f"sqlite:///{tmp_path / db_name}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_session():
        with session_factory() as s:
            yield s
            s.commit()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), session_factory


def test_dispatch_failure_persists_across_sessions(tmp_path, monkeypatch):
    # Round-2 fix: test_dispatch_failure_marks_item_failed_and_notifies above
    # cannot detect a regression that downgrades the except block's
    # session.commit() to session.flush() (or deletes it) -- it passed
    # unchanged under both in review. This test can: it asserts through a
    # brand-new session on the same file-backed engine, which only sees
    # committed data.
    client, session_factory = _durable_client(tmp_path, "render_fail.sqlite")

    with session_factory() as seed_session:
        item = ContentItem(slug="w32-video-fail", topic="t", status="idea")
        seed_session.add(item)
        seed_session.commit()
        item_id = item.id

    class BoomDispatcher:
        def dispatch(self, item_id):
            raise RuntimeError("cloud run unavailable")

    monkeypatch.setattr(items_api, "get_dispatcher", lambda s: BoomDispatcher())
    notes = []
    monkeypatch.setattr(items_api, "line_notify", notes.append)

    resp = client.post(
        f"/api/items/{item_id}/render", json={"format": "tips"}, headers=AUTH
    )
    assert resp.status_code == 502

    with session_factory() as fresh_session:
        row = fresh_session.get(ContentItem, item_id)
        assert row.status == "failed"
        assert row.render_error and "cloud run unavailable" in row.render_error


def test_dispatch_success_persists_across_sessions(tmp_path, monkeypatch):
    # Companion to the failure-path test above -- and NOT the same shape.
    # get_session's own generator commits after the handler returns
    # (mirroring app/db.py), on success as well as on the code path this
    # test exercises. So by the time the whole request has finished, the
    # row is committed either way, regardless of whether the handler's OWN
    # session.commit() (called before dispatch(), per the commit-before-
    # dispatch fix) ran or was downgraded to flush()/deleted -- checked this
    # empirically: an end-of-request assertion here does NOT fail when that
    # commit is removed.
    #
    # What actually distinguishes commit-before-dispatch from flush-before-
    # dispatch is durability AT THE MOMENT dispatch() runs, mid-request --
    # exactly the render-worker race the fix exists for (a worker opening
    # its own session/connection against the same row before this request's
    # transaction commits). So the dispatcher stub here reads the row back
    # through a brand-new, independent session from INSIDE dispatch()
    # itself, synchronously, before the request handler ever returns.
    client, session_factory = _durable_client(tmp_path, "render_ok.sqlite")

    with session_factory() as seed_session:
        item = ContentItem(slug="w32-video-ok", topic="t", status="idea")
        seed_session.add(item)
        seed_session.commit()
        item_id = item.id

    seen = {}

    class ProbeDispatcher:
        def dispatch(self, dispatched_item_id):
            with session_factory() as probe_session:
                row = probe_session.get(ContentItem, dispatched_item_id)
                seen["status"] = row.status
                seen["format"] = row.format
                seen["scenario"] = row.scenario

    monkeypatch.setattr(items_api, "get_dispatcher", lambda s: ProbeDispatcher())

    resp = client.post(
        f"/api/items/{item_id}/render",
        json={"format": "demo", "scenario": "fixture-demo"}, headers=AUTH,
    )
    assert resp.status_code == 200
    assert seen["status"] == "rendering"
    assert seen["format"] == "demo"
    assert seen["scenario"] == "fixture-demo"
