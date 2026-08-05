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
    report = run_tick(db, {"x": adapter}, NOW, notify=notes.append)
    assert pub.status == "pending" and pub.attempts == 0
    state = db.get(ChannelState, "x")
    assert state is not None and state.needs_reauth is True
    assert len(notes) == 1
    assert report["auth_paused"] == 1


def test_bare_exception_is_retried_like_channel_error(db):
    # A non-ChannelError exception (httpx timeout, adapter bug, etc.) must not
    # propagate out of run_tick: it should be treated like a retryable
    # ChannelError so the transaction still commits and earlier successes in
    # the same tick aren't rolled back and re-published next tick.
    item, pub = seed(db)
    adapter = StubAdapter([RuntimeError("dns boom")])
    report = run_tick(db, {"dryrun": adapter}, NOW, notify=lambda m: None)
    assert report["retried"] == 1
    assert pub.status == "pending" and pub.attempts == 1
    assert "dns boom" in pub.last_error


def test_missing_adapter_increments_skipped_counter(db):
    item, pub = seed(db, channel="tiktok")
    report = run_tick(db, {}, NOW, notify=lambda m: None)
    assert report["skipped"] == 1
    assert pub.status == "pending" and pub.attempts == 0


def test_earlier_success_survives_later_bare_exception_in_same_tick(db):
    # This is the actual regression the fix guards against: run_tick must
    # finish and return a report (so session.flush() runs and get_session's
    # later commit can persist everything) even when a LATER publication in
    # the same tick blows up with a non-ChannelError exception. If the bare
    # exception were allowed to propagate, the whole tick's transaction
    # would roll back and this publication -- already marked posted earlier
    # in this same call -- would be re-published on the next tick.
    item_a, pub_a = seed(db, channel="dryrun")
    item_b, pub_b = seed(db, channel="line")
    adapter_a = StubAdapter([PublishOutcome(status="posted", post_ref="p1")])
    adapter_b = StubAdapter([RuntimeError("boom")])
    report = run_tick(
        db, {"dryrun": adapter_a, "line": adapter_b}, NOW, notify=lambda m: None
    )
    assert report["posted"] == 1
    assert report["retried"] == 1
    assert pub_a.status == "posted" and pub_a.post_ref == "p1"
    assert pub_b.status == "pending" and pub_b.attempts == 1
