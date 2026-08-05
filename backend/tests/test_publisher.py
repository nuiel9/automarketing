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
