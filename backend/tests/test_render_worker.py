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
                        lambda segs, hook, work_dir, **kw: (str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")))
    for name in ("f.mp4", "p.jpg"):
        (tmp_path / name).write_bytes(b"x")
    saved = {}
    monkeypatch.setattr(worker, "get_store", _fake_store(saved))

    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "in_review"
    assert item.media_path.startswith("stored/")
    assert item.render_error is None


def test_compose_called_with_subtitles_true_for_demo_format(db, tmp_path, monkeypatch):
    # A demo screen-recording has no text of its own, so the burned
    # narration subtitle is essential -- worker.py must ask compose() for it.
    item = _item(db)
    seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
    monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))
    calls = []

    def _fake_compose(segs, hook, work_dir, **kw):
        calls.append(kw)
        (tmp_path / "f.mp4").write_bytes(b"x")
        (tmp_path / "p.jpg").write_bytes(b"x")
        return str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")

    monkeypatch.setattr(worker, "compose", _fake_compose)
    monkeypatch.setattr(worker, "get_store", _fake_store({}))

    worker.render_item(db, item.id, notify=lambda m: None)

    # Assert the one flag this test is about, not the whole kwargs dict --
    # an exact-dict match fails whenever compose() gains an unrelated
    # argument (it did, when music was added), which says nothing about
    # subtitles.
    assert [c["subtitles"] for c in calls] == [True]


def test_compose_called_with_subtitles_false_for_tips_format(db, tmp_path, monkeypatch):
    # Tips cards already display their headline and body as on-screen text,
    # so burning the same narration over them would be redundant and
    # collide with the card's own text.
    item = ContentItem(slug="w32-tips-y", topic="หัวข้อ", status="rendering", format="tips")
    db.add(item); db.commit()
    seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
    monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))
    calls = []

    def _fake_compose(segs, hook, work_dir, **kw):
        calls.append(kw)
        (tmp_path / "f.mp4").write_bytes(b"x")
        (tmp_path / "p.jpg").write_bytes(b"x")
        return str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")

    monkeypatch.setattr(worker, "compose", _fake_compose)
    monkeypatch.setattr(worker, "get_store", _fake_store({}))

    worker.render_item(db, item.id, notify=lambda m: None)

    assert [c["subtitles"] for c in calls] == [False]


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
                        lambda segs, hook, work_dir, **kw: (str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")))
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
                        lambda segs, hook, work_dir, **kw: (str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")))
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


def test_broken_strategy_file_costs_the_music_not_the_render(db, tmp_path, monkeypatch):
    """A malformed or missing strategy.yaml must not fail a render.

    Before music existed, a demo render never read strategy.yaml at all, so
    making the render depend on parsing it would newly break renders that
    used to work. Music is a polish layer -- losing the bed is not worth
    dropping a finished video on the floor.
    """
    item = _item(db)
    seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
    monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))

    def _boom(path):
        raise ValueError("strategy.yaml is not valid yaml")

    monkeypatch.setattr(worker, "load_strategy", _boom)
    calls = []

    def _fake_compose(segs, hook, work_dir, **kw):
        calls.append(kw)
        (tmp_path / "f.mp4").write_bytes(b"x")
        (tmp_path / "p.jpg").write_bytes(b"x")
        return str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")

    monkeypatch.setattr(worker, "compose", _fake_compose)
    monkeypatch.setattr(worker, "get_store", _fake_store({}))

    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "in_review"
    assert calls[0]["music_track"] is None


def test_a_valid_strategy_actually_selects_music_for_both_formats(db, tmp_path, monkeypatch):
    """The positive case: with a real config, a track reaches compose().

    Every other test in this file runs with no strategy.yaml on the worker's
    cwd, so _music_for takes its degradation branch and hands compose()
    music_track=None. Without this test, _music_for could return None
    unconditionally and the whole suite would still pass -- while every
    shipped video came out silent of music.
    """
    import app.video.music as music_mod
    from app.strategy import MusicConfig, Strategy

    root = tmp_path / "music"
    root.mkdir()
    for name in ("city-sunshine", "inspiration"):
        (root / f"{name}.mp3").write_bytes(b"not really an mp3, only the lookup is under test")

    strategy = Strategy(
        voice="v", audiences=["a"], banned_words=[], platform_notes={},
        music=MusicConfig(tips=["city-sunshine"], demo=["inspiration"]),
    )
    monkeypatch.setattr(worker, "load_strategy", lambda path: strategy)
    # pick_track binds MUSIC_ROOT as a default argument at import time, so the
    # root has to be threaded through rather than patched onto the module.
    monkeypatch.setattr(worker, "pick_track",
                        lambda ids, key: music_mod.pick_track(ids, key, str(root)))

    for fmt, expected in (("demo", "inspiration.mp3"), ("tips", "city-sunshine.mp3")):
        item = ContentItem(slug=f"w32-{fmt}-music", topic="หัวข้อ", status="rendering",
                           format=fmt, scenario="fixture-demo" if fmt == "demo" else None)
        db.add(item); db.commit()
        seg = Segment("clip.mp4", Narration("t", "n.wav", 1.0))
        monkeypatch.setattr(worker, "_render_segments", lambda *a, **k: ([seg], "hook"))
        calls = []

        def _fake_compose(segs, hook, work_dir, **kw):
            calls.append(kw)
            (tmp_path / "f.mp4").write_bytes(b"x")
            (tmp_path / "p.jpg").write_bytes(b"x")
            return str(tmp_path / "f.mp4"), str(tmp_path / "p.jpg")

        monkeypatch.setattr(worker, "compose", _fake_compose)
        monkeypatch.setattr(worker, "get_store", _fake_store({}))

        worker.render_item(db, item.id, notify=lambda m: None)

        db.refresh(item)
        assert item.status == "in_review", f"{fmt} render failed: {item.render_error}"
        assert calls[0]["music_track"] is not None, f"{fmt} got no music track"
        assert calls[0]["music_track"].endswith(expected), (
            f"{fmt} should draw from its own configured list, got {calls[0]['music_track']}"
        )
        assert calls[0]["music_lufs"] == -33.0


def _motion_item(db, **kw):
    item = ContentItem(slug="w32-ad", topic="เทคนิคจำศัพท์", status="rendering",
                       format="motion_ad", **kw)
    db.add(item); db.commit()
    return item


def _stub_motion_ad(monkeypatch, tmp_path, *, generate, poll=None):
    from app.strategy import MusicConfig, Strategy
    from app.video.ad_copy import AdCopy

    # vo_script deliberately exceeds its 160-char cap (_CAPS in ad_copy.py):
    # as_payload() and model_dump() must differ, or an assertion comparing
    # generate_ad's payload against as_payload() can't tell the capped
    # (gate-checked) text from the raw fields -- every field being short
    # made that comparison a no-op before this change.
    copy = AdCopy(kicker="k", name="Eduverse One", tagline="t", hl1="a",
                  hl2="b", promo="p", cta="c", vo_script="v" * 170)
    # A real Strategy, not a real strategy.yaml: unlike production/Docker,
    # local test runs have no "./strategy.yaml" reachable from backend/'s
    # cwd (every other module that needs one -- test_items_api.py,
    # test_render_api.py -- monkeypatches load_strategy for the same
    # reason). music.motion_ad mirrors the repo-root strategy.yaml so the
    # real (unstubbed) pick_track_id still returns a real track id.
    strategy = Strategy(
        voice="v", audiences=["a"], banned_words=[], platform_notes={},
        music=MusicConfig(motion_ad=["inspiration", "advertime"]),
    )
    monkeypatch.setattr(worker, "capture", lambda url, out, side=1080: out)
    monkeypatch.setattr(worker, "to_data_uri", lambda p: "data:image/png;base64,AAA")
    monkeypatch.setattr(worker, "load_strategy", lambda path: strategy)
    monkeypatch.setattr(worker, "write_ad_copy", lambda topic, strategy: copy)
    monkeypatch.setattr(worker, "generate_ad", generate)
    monkeypatch.setattr(worker, "poll", poll or (lambda job_id, timeout: "https://x/y.mp4"))
    monkeypatch.setattr(worker, "download", lambda url: b"MP4DATA")
    monkeypatch.setattr(worker, "get_store", _fake_store({}))
    return copy


def test_motion_ad_stores_media_and_reaches_review(db, tmp_path, monkeypatch):
    item = _motion_item(db)
    calls = []

    def _generate(photo, brief, copy_payload, track_id):
        calls.append((photo, brief, copy_payload, track_id))
        return "job-1"

    copy = _stub_motion_ad(monkeypatch, tmp_path, generate=_generate)

    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert item.status == "in_review"
    assert item.media_path.startswith("stored/")
    assert item.aivdo_job_id == "job-1"
    # Constraint 1: generate_ad must receive the CAPPED payload the
    # banned-words gate actually checked, never the raw AdCopy fields.
    assert calls[0][2] == copy.as_payload()
    assert calls[0][3] in ("inspiration", "advertime")


def test_job_id_is_persisted_before_polling(db, tmp_path, monkeypatch):
    """The 5 credits are spent the moment generate returns.

    If we only saved the id after a successful poll, a crash mid-poll would
    lose it -- and the retry would generate a second ad and pay again.

    This must observe ORDERING directly, not infer it from what a query can
    see. `db` here is the very same Session `_render_motion_ad` writes
    through, and SQLAlchemy's default `expire_on_commit=True` only expires
    attributes on ITS OWN commit -- it does not stop the identity map from
    handing back a pending in-memory value to `db.get(...)` regardless of
    whether a commit happened first. So a `db.get()` read from inside the
    poll stub would return "job-2" even if the interim `session.commit()`
    were deleted entirely and only the trailing `finally: session.commit()`
    ran -- proving nothing. Wrapping `commit` and `poll` to append to a
    shared, ordered event log is what actually distinguishes "committed,
    then polled" from "polled, then committed at the end".
    """
    item = _motion_item(db)
    events = []
    real_commit = db.commit

    def _tracked_commit():
        # Captured at call time, not after: item.aivdo_job_id already holds
        # whatever the worker assigned to it before calling commit().
        events.append(f"commit:{item.aivdo_job_id}")
        real_commit()

    monkeypatch.setattr(db, "commit", _tracked_commit)

    def _poll(job_id, timeout):
        events.append(f"poll:{job_id}")
        return "https://x/y.mp4"

    _stub_motion_ad(monkeypatch, tmp_path,
                    generate=lambda *a, **k: "job-2", poll=_poll)

    worker.render_item(db, item.id, notify=lambda m: None)

    assert "commit:job-2" in events, "the new job id must be committed at some point"
    assert events.index("commit:job-2") < events.index("poll:job-2"), (
        f"job id must be committed before polling, got order: {events}"
    )


def test_retry_resumes_an_existing_job_instead_of_paying_again(db, tmp_path, monkeypatch):
    item = _motion_item(db, aivdo_job_id="job-existing")
    calls = []

    def _generate(*a, **k):
        calls.append(a)
        return "job-new"

    _stub_motion_ad(monkeypatch, tmp_path, generate=_generate)

    worker.render_item(db, item.id, notify=lambda m: None)

    db.refresh(item)
    assert calls == [], "an item with a job id must not dispatch a second ad"
    assert item.aivdo_job_id == "job-existing"
    assert item.status == "in_review"


def test_banned_copy_fails_the_item_without_calling_aivdo(db, tmp_path, monkeypatch):
    from app.video.ad_copy import BannedCopyError

    item = _motion_item(db)
    called = []
    _stub_motion_ad(monkeypatch, tmp_path,
                    generate=lambda *a, **k: called.append(1) or "job-x")

    def _boom(topic, strategy):
        raise BannedCopyError(["รับประกันสอบติด"])

    monkeypatch.setattr(worker, "write_ad_copy", _boom)
    notes = []

    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert "รับประกันสอบติด" in item.render_error
    assert called == [], "banned copy must never reach AIVDO -- it costs credits"
    assert notes


def test_out_of_credits_produces_a_distinct_message(db, tmp_path, monkeypatch):
    from app.video.aivdo import OutOfCreditsError

    item = _motion_item(db)

    def _broke(*a, **k):
        raise OutOfCreditsError("AIVDO is out of credits: Need 5.")

    _stub_motion_ad(monkeypatch, tmp_path, generate=_broke)
    notes = []

    worker.render_item(db, item.id, notify=notes.append)

    db.refresh(item)
    assert item.status == "failed"
    assert "credits" in item.render_error.lower()
    assert notes
