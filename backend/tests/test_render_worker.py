import pytest

import app.video.worker as worker
from app.models import ContentItem
from app.video.compose import Segment
from app.video.demo import RenderStepError
from app.video.scenario import ScenarioError
from app.video.tips import TipsError
from app.video.tts import Narration


def _item(db, **kw):
    item = ContentItem(slug="w32-demo-x", topic="หัวข้อ", status="rendering",
                       format="demo", scenario="fixture-demo", **kw)
    db.add(item); db.commit()
    return item


def _fake_store(saved: dict):
    return lambda s: type("S", (), {
        "save": lambda self, data, filename: saved.setdefault(filename, "stored/" + filename)
    })()


def test_successful_render_stores_media_and_moves_to_review(db, tmp_path, monkeypatch):
    item = _item(db)
    seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
    monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))
    monkeypatch.setattr(worker, "compose",
                        lambda segs, hook, work_dir: (str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")))
    for name in ("f.mp4", "p.jpg"):
        (tmp_path / name).write_bytes(b"x")
    saved = {}
    monkeypatch.setattr(worker, "get_store", _fake_store(saved))

    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "in_review"
    assert item.media_path.startswith("stored/")
    assert item.render_error is None


def test_poster_upload_failure_leaves_media_path_none_and_marks_failed(db, tmp_path, monkeypatch):
    # Fix 1 (post-review): item.media_path must only be assigned once BOTH
    # the video and the poster upload have succeeded. Assigning it right
    # after the video upload would let a poster-upload failure land the
    # item in "failed" while media_path still pointed at a real, playable
    # video -- both items.py's media_url and the /media/{token} route gate
    # only on media_path being truthy, never on status.
    item = _item(db)
    seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
    monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))
    monkeypatch.setattr(worker, "compose",
                        lambda segs, hook, work_dir: (str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")))
    for name in ("f.mp4", "p.jpg"):
        (tmp_path / name).write_bytes(b"x")

    def _store_factory(settings):
        class S:
            def save(self, data, filename):
                if filename == "poster.jpg":
                    raise RuntimeError("disk full")
                return "stored/" + filename
        return S()

    monkeypatch.setattr(worker, "get_store", _store_factory)
    notes = []

    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert item.media_path is None
    assert "disk full" in item.render_error
    assert notes


def test_success_commit_failure_is_logged_and_reraised(db, tmp_path, monkeypatch, caplog):
    # Fix 2 (post-review): a commit failure after a successful render must
    # not be silent -- it's logged (in addition to being re-raised so the
    # caller still learns about it), rather than leaving the item stuck in
    # "rendering" with nothing recorded anywhere.
    item = _item(db)
    seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
    monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))
    monkeypatch.setattr(worker, "compose",
                        lambda segs, hook, work_dir: (str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")))
    for name in ("f.mp4", "p.jpg"):
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.setattr(worker, "get_store", _fake_store({}))

    def _boom_commit():
        raise RuntimeError("db is down")

    monkeypatch.setattr(db, "commit", _boom_commit)

    with caplog.at_level("ERROR", logger="app.video.worker"):
        with pytest.raises(RuntimeError, match="db is down"):
            worker.render_item(db, item.id, notify=lambda m: None)

    assert any("failed to commit result" in r.message for r in caplog.records)


def test_upload_screenshot_failure_logs_warning(tmp_path, monkeypatch, caplog):
    # Fix 3 (post-review): a bare "except Exception: return None" made an
    # upload failure indistinguishable from "no screenshot existed". A
    # log.warning makes a future regression diagnosable.
    shot = tmp_path / "s.png"
    shot.write_bytes(b"x")

    def _boom_store(settings):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(worker, "get_store", _boom_store)

    with caplog.at_level("WARNING", logger="app.video.worker"):
        ref = worker._upload_screenshot(str(shot))

    assert ref is None
    assert any("failed to upload failure screenshot" in r.message for r in caplog.records)


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


def test_step_failure_uploads_screenshot_and_appends_reference(db, monkeypatch, tmp_path):
    # Correction 3: the screenshot from a RenderStepError must not be
    # discarded -- it's uploaded via the media store and its path appended
    # to render_error so the founder can actually see the failing step.
    item = _item(db)
    shot = tmp_path / "fail_step_2.png"
    shot.write_bytes(b"fake-png-bytes")

    def _boom(*a, **k):
        raise RenderStepError("step 2 (click #go): timeout", 2, str(shot))

    monkeypatch.setattr(worker, "_render_segments", _boom)
    saved = {}
    monkeypatch.setattr(worker, "get_store", _fake_store(saved))

    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "failed"
    assert saved == {"fail_step_2.png": "stored/fail_step_2.png"}
    assert "[screenshot: stored/fail_step_2.png]" in item.render_error
    assert "step 2" in item.render_error


def test_screenshot_reference_survives_notify_truncation_on_long_message(db, monkeypatch, tmp_path):
    # A real Playwright timeout error carries a multi-hundred-char "Call
    # log:" block, so the message alone can fill notify's 300-char budget.
    # The screenshot ref must be appended after truncation, not swallowed
    # by it -- otherwise the founder's LINE alert (the thing they actually
    # read) never shows the screenshot even though render_error in the DB
    # does.
    item = _item(db)
    shot = tmp_path / "fail_step_2.png"
    shot.write_bytes(b"fake-png-bytes")
    long_detail = "step 2 (click #go): " + ("timeout waiting for selector; " * 20)

    def _boom(*a, **k):
        raise RenderStepError(long_detail, 2, str(shot))

    monkeypatch.setattr(worker, "_render_segments", _boom)
    saved = {}
    monkeypatch.setattr(worker, "get_store", _fake_store(saved))
    notes = []

    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert "[screenshot: stored/fail_step_2.png]" in item.render_error
    assert notes and "[screenshot: stored/fail_step_2.png]" in notes[0]


def test_step_failure_screenshot_missing_on_disk_does_not_crash(db, monkeypatch):
    # RenderStepError carries a screenshot_path that may not resolve to a
    # real file (e.g. the brief's own test uses "/tmp/shot.png"); the upload
    # attempt must degrade gracefully rather than raising out of the except
    # handler and losing the original error message and notification.
    item = _item(db)
    notes = []

    def _boom(*a, **k):
        raise RenderStepError("step 2 (click #go): timeout", 2, "/tmp/does-not-exist-shot.png")

    monkeypatch.setattr(worker, "_render_segments", _boom)

    def _store_that_blows_up(settings):
        raise AssertionError("get_store must not be called for a nonexistent screenshot path")

    monkeypatch.setattr(worker, "get_store", _store_that_blows_up)

    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert "step 2" in item.render_error
    assert "[screenshot:" not in item.render_error
    assert notes


def test_failure_when_not_rendering_still_records_error_and_notifies(db, monkeypatch):
    # Correction 2: even if the item wasn't in "rendering" status when the
    # failure happened (so transition(item, "failed") is skipped to avoid an
    # InvalidTransition), render_error must still be set and notify called.
    item = ContentItem(slug="w32-demo-y", topic="topic", status="idea",
                       format="demo", scenario="fixture-demo")
    db.add(item); db.commit()
    notes = []

    def _boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(worker, "_render_segments", _boom)
    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "idea"          # transition("failed") skipped: guard held
    assert item.render_error == "boom"
    assert notes and "render failed" in notes[0].lower()


def test_tips_error_marks_failed_not_crash(db, monkeypatch):
    item = ContentItem(slug="w32-tips-x", topic="หัวข้อ", status="rendering", format="tips")
    db.add(item); db.commit()
    notes = []

    def _boom(*a, **k):
        raise TipsError("tips model returned zero cards")

    monkeypatch.setattr(worker, "_render_segments", _boom)
    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert "zero cards" in item.render_error
    assert notes


def test_scenario_error_marks_failed_not_crash(db, monkeypatch):
    item = _item(db)
    notes = []

    def _boom(*a, **k):
        raise ScenarioError("scenario not found: bogus")

    monkeypatch.setattr(worker, "_render_segments", _boom)
    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert "scenario not found" in item.render_error
    assert notes


def test_unrenderable_format_fails_loudly(db):
    # Exercises the real (unmocked) _render_segments dispatch: an unknown
    # format must be a clean failed-item outcome, not a crash.
    item = ContentItem(slug="w32-mystery-x", topic="หัวข้อ", status="rendering", format="mystery")
    db.add(item); db.commit()
    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "failed"
    assert "mystery" in item.render_error


def test_main_reads_item_id_env_and_delegates(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "render_item", lambda session, item_id, **kw: calls.append(item_id))
    monkeypatch.setenv("ITEM_ID", "abc123")

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def commit(self):
            pass

    monkeypatch.setattr(worker, "SessionLocal", lambda: FakeSession())

    worker.main()

    assert calls == ["abc123"]
