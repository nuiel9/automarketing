from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.captions import CaptionError, write_captions
from app.config import get_settings
from app.db import get_session
from app.media import get_store
from app.models import Caption, ContentItem, Publication
from app.state import InvalidTransition, transition
from app.strategy import banned_violations, load_strategy
from app.utm import campaign_slug

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])

CHANNELS = ["tiktok", "youtube", "instagram", "facebook", "x", "line"]


def item_json(item: ContentItem) -> dict:
    settings = get_settings()
    strategy = load_strategy(settings.strategy_path)
    return {
        "id": item.id,
        "slug": item.slug,
        "topic": item.topic,
        "hook": item.hook,
        "link": item.link,
        "status": item.status,
        "media_token": item.media_token,
        "media_url": f"{settings.public_base_url}/media/{item.media_token}"
        if item.media_path
        else None,
        "reject_reason": item.reject_reason,
        "banned_violations": banned_violations(
            strategy, [c.body for c in item.captions] + [c.title or "" for c in item.captions]
        ),
        "captions": [
            {
                "channel": c.channel,
                "title": c.title,
                "body": c.body,
                "hashtags": c.hashtags,
                "edited_by_human": c.edited_by_human,
            }
            for c in item.captions
        ],
        "publications": [
            {
                "channel": p.channel,
                "status": p.status,
                "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                "post_ref": p.post_ref,
                "attempts": p.attempts,
                "last_error": p.last_error,
            }
            for p in item.publications
        ],
    }


def _generate(item: ContentItem, session: Session) -> str | None:
    settings = get_settings()
    try:
        caps = write_captions(item.topic, item.hook, load_strategy(settings.strategy_path))
    except CaptionError as exc:
        return str(exc)
    item.captions.clear()
    for channel in CHANNELS:
        c = getattr(caps, channel)
        item.captions.append(
            Caption(
                channel=channel,
                title=c.title,
                body=c.body,
                hashtags=c.hashtags,
                edited_by_human=False,
            )
        )
    if item.status == "idea":
        transition(item, "in_review")
    return None


@router.post("/items", status_code=201)
def create_item(
    topic: str = Form(...),
    hook: str | None = Form(None),
    link: str | None = Form(None),
    file: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    item = ContentItem(
        slug=campaign_slug("founder_clip", topic, date.today()),
        topic=topic,
        hook=hook,
        link=link,
        status="idea",
    )
    if file is not None:
        item.media_path = get_store(get_settings()).save(file.file, file.filename or "clip.mp4")
    caption_error = _generate(item, session)
    session.add(item)
    session.flush()
    body = item_json(item)
    if caption_error:
        body["caption_error"] = caption_error
    return body


def _get(item_id: str, session: Session) -> ContentItem:
    item = session.get(ContentItem, item_id)
    if item is None:
        raise HTTPException(404)
    return item


@router.post("/items/{item_id}/captions")
def regenerate(item_id: str, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    error = _generate(item, session)
    if error:
        raise HTTPException(502, f"caption generation failed: {error}")
    return item_json(item)


@router.get("/items")
def list_items(status: str | None = None, session: Session = Depends(get_session)):
    q = select(ContentItem).order_by(ContentItem.created_at.desc())
    if status:
        q = q.where(ContentItem.status == status)
    return [item_json(i) for i in session.scalars(q).all()]


@router.get("/items/{item_id}")
def get_item(item_id: str, session: Session = Depends(get_session)):
    return item_json(_get(item_id, session))


class CaptionEdit(BaseModel):
    channel: str
    title: str | None = None
    body: str
    hashtags: list[str] = []


@router.put("/items/{item_id}/captions")
def edit_caption(item_id: str, edit: CaptionEdit, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    for c in item.captions:
        if c.channel == edit.channel:
            c.title, c.body, c.hashtags = edit.title, edit.body, edit.hashtags
            c.edited_by_human = True
            return item_json(item)
    raise HTTPException(404, "no caption for channel")


class ApproveBody(BaseModel):
    scheduled_at: datetime
    channels: list[str]


@router.post("/items/{item_id}/approve")
def approve(item_id: str, body: ApproveBody, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    strategy = load_strategy(get_settings().strategy_path)
    violations = banned_violations(
        strategy, [c.body for c in item.captions] + [c.title or "" for c in item.captions]
    )
    if violations:
        raise HTTPException(422, f"banned words present: {', '.join(violations)}")
    have = {c.channel for c in item.captions}
    missing = [ch for ch in body.channels if ch not in have and ch != "dryrun"]
    if missing:
        raise HTTPException(422, f"no captions for: {', '.join(missing)}")
    try:
        transition(item, "approved")
        transition(item, "scheduled")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    item.channels = body.channels
    for channel in body.channels:
        item.publications.append(
            Publication(
                channel=channel,
                scheduled_at=body.scheduled_at,
                status="pending",
                attempts=0,
            )
        )
    return item_json(item)


class RejectBody(BaseModel):
    reason: str


@router.post("/items/{item_id}/reject")
def reject(item_id: str, body: RejectBody, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    try:
        transition(item, "rejected")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    item.reject_reason = body.reason
    return item_json(item)


@router.post("/items/{item_id}/retry")
def retry(item_id: str, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    try:
        transition(item, "scheduled")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    for p in item.publications:
        if p.status == "failed":
            p.status, p.attempts, p.next_attempt_at, p.last_error = "pending", 0, None, None
    return item_json(item)
