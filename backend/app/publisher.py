from datetime import datetime, timedelta
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
        "skipped": 0, "auth_paused": 0,
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
        else:
            pub.status = "pending_external"
            pub.external_state = outcome.state
            pub.next_attempt_at = now + timedelta(seconds=60)
            report["pending"] += 1
        _settle_item(pub.item)

    session.flush()
    return report
