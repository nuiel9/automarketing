from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import or_, select

from app.channels.base import (
    ChannelAdapter, ChannelAuthError, ChannelError, PublishOutcome, PublishRequest,
)
from app.config import get_settings
from app.models import ChannelState, ContentItem, Publication
from app.state import transition
from app.utm import with_utm

MAX_ATTEMPTS = 3
PENDING_MAX_AGE = timedelta(hours=1)
RENDER_MAX_AGE = timedelta(minutes=20)


def _aware(dt: datetime) -> datetime:
    # SQLite (used in tests) doesn't round-trip tzinfo on DateTime(timezone=True)
    # columns the way Postgres does in production, so a value freshly loaded
    # from the DB can come back naive even though it was written as UTC.
    # `now` (from datetime.now(timezone.utc)) is always aware, so normalize
    # here rather than let the subtraction raise.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _build_request(pub: Publication) -> PublishRequest:
    item = pub.item
    caption = next((c for c in item.captions if c.channel == pub.channel), None)
    body_parts = [caption.body if caption else item.topic]
    if caption and caption.hashtags:
        body_parts.append(" ".join(caption.hashtags))
    if item.link:
        body_parts.append(with_utm(item.link, pub.channel, item.slug))
    media_url = (
        f"{get_settings().public_base_url}/media/{item.media_token}"
        if item.media_path
        else None
    )
    return PublishRequest(
        item_id=item.id,
        channel=pub.channel,
        title=caption.title if caption else None,
        body="\n\n".join(body_parts),
        media_url=media_url,
        state=pub.external_state,
    )


def _settle_item(item: ContentItem) -> None:
    statuses = {p.status for p in item.publications}
    if statuses <= {"posted"} and item.status == "scheduled":
        transition(item, "posted")
    elif "failed" in statuses and item.status == "scheduled":
        transition(item, "failed")


def _retry_or_fail(
    pub: Publication,
    report: dict,
    notify: Callable[[str], None],
    now: datetime,
    error_text: str,
) -> None:
    pub.attempts += 1
    pub.last_error = error_text
    if pub.attempts >= MAX_ATTEMPTS:
        pub.status = "failed"
        report["failed"] += 1
        notify(f"[AutoMarketing] publish failed on {pub.channel}: {error_text}")
    else:
        pub.next_attempt_at = now + timedelta(minutes=2**pub.attempts)
        report["retried"] += 1
    _settle_item(pub.item)


def run_tick(
    session,
    adapters: dict[str, ChannelAdapter],
    now: datetime,
    notify: Callable[[str], None],
) -> dict:
    report = {
        "posted": 0, "pending": 0, "failed": 0, "retried": 0,
        "skipped": 0, "auth_paused": 0, "render_failed": 0,
    }
    due = session.scalars(
        select(Publication)
        .where(
            Publication.status.in_(["pending", "pending_external"]),
            Publication.scheduled_at <= now,
            or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now),
        )
        .with_for_update(skip_locked=True)
    ).all()

    for pub in due:
        adapter = adapters.get(pub.channel)
        if adapter is None:
            report["skipped"] += 1
            continue
        try:
            outcome: PublishOutcome = adapter.publish(_build_request(pub))
        except ChannelAuthError as exc:
            state = session.get(ChannelState, pub.channel) or ChannelState(channel=pub.channel)
            state.needs_reauth = True
            state.note = str(exc)
            session.merge(state)
            pub.next_attempt_at = now + timedelta(hours=1)
            report["auth_paused"] += 1
            notify(f"[AutoMarketing] {pub.channel} needs re-auth: {exc}")
            continue
        except ChannelError as exc:
            _retry_or_fail(pub, report, notify, now, str(exc))
            continue
        except Exception as exc:
            # A bare (non-ChannelError) exception from an adapter — httpx
            # timeout, DNS failure, adapter bug — must never propagate out of
            # run_tick: that would abort get_session's commit and roll back
            # publications already marked posted earlier in this same tick,
            # causing them to be re-published on the next tick. Treat it like
            # a retryable ChannelError instead.
            _retry_or_fail(pub, report, notify, now, repr(exc))
            continue

        if outcome.status == "posted":
            pub.status = "posted"
            pub.posted_at = now
            pub.post_ref = outcome.post_ref
            report["posted"] += 1
        elif (
            pub.status == "pending_external"
            and now - _aware(pub.scheduled_at) > PENDING_MAX_AGE
        ):
            # A pending_external publication that has been polling for too
            # long (e.g. an IG Reels container stuck IN_PROGRESS) must not
            # be re-pended forever -- fail it explicitly rather than leaving
            # the item in "scheduled" indefinitely. The pub.status == "pending_external"
            # guard matters: this branch also runs for a publication's *first*
            # pending outcome (e.g. an IG container just created, or a first
            # attempt on a publication whose scheduled_at is already old
            # because of a missed cron window or an earlier auth pause) --
            # those must still get their first poll rather than being failed
            # before ever checking status once.
            error_text = "pending timeout after 1h"
            pub.status = "failed"
            pub.last_error = error_text
            report["failed"] += 1
            notify(f"[AutoMarketing] publish failed on {pub.channel}: {error_text}")
        else:
            pub.status = "pending_external"
            pub.external_state = outcome.state
            pub.next_attempt_at = now + timedelta(seconds=60)
            report["pending"] += 1
        _settle_item(pub.item)

    stuck = session.scalars(
        select(ContentItem).where(ContentItem.status == "rendering")
    ).all()
    for item in stuck:
        if now - _aware(item.updated_at) <= RENDER_MAX_AGE:
            continue
        item.render_error = "render timed out"
        transition(item, "failed")
        report["render_failed"] += 1
        notify(f"[AutoMarketing] render stuck over 20 min, failed: {item.slug}")

    session.flush()
    return report
