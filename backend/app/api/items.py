import os
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, field_validator
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
from app.video.dispatcher import get_dispatcher
from app.video.scenario import ScenarioError, load_scenario

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
        "scenario": item.scenario,
        "render_error": item.render_error,
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
                # Explicit: mirrors the ORM column default, but that default only
                # applies at flush/INSERT time -- item_json() may read this field
                # on a still-transient instance beforehand. Do not remove.
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
        # Explicit: ContentItem.status has an ORM default="idea", but that only
        # applies at flush/INSERT time -- _generate() below branches on
        # item.status before this instance is ever flushed. Do not remove.
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
    if item.status not in ("idea", "in_review"):
        raise HTTPException(409, "captions are locked once approved")
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
    if item.status not in ("idea", "in_review"):
        raise HTTPException(409, "captions are locked once approved")
    for c in item.captions:
        if c.channel == edit.channel:
            c.title, c.body, c.hashtags = edit.title, edit.body, edit.hashtags
            c.edited_by_human = True
            return item_json(item)
    raise HTTPException(404, "no caption for channel")


class ApproveBody(BaseModel):
    scheduled_at: datetime
    channels: list[str]

    @field_validator("scheduled_at")
    @classmethod
    def _normalize_scheduled_at(cls, value: datetime) -> datetime:
        # The publisher (Task 9) compares this against datetime.now(timezone.utc);
        # a naive value would raise TypeError there and be ambiguous in storage.
        # Assume UTC for naive input, otherwise convert aware input to UTC.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


@router.post("/items/{item_id}/approve")
def approve(item_id: str, body: ApproveBody, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    if not body.channels:
        raise HTTPException(422, "channels must not be empty")
    enabled = set(get_settings().channels())
    not_enabled = [ch for ch in body.channels if ch not in enabled]
    if not_enabled:
        raise HTTPException(422, f"channels not enabled: {', '.join(not_enabled)}")
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
                # Explicit: mirrors Publication's ORM defaults (status="pending",
                # attempts=0), but those only apply at flush/INSERT time and this
                # request's response is built from the still-transient instance.
                # Do not remove.
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
            p.status, p.attempts, p.next_attempt_at, p.last_error, p.external_state = (
                "pending",
                0,
                None,
                None,
                None,
            )
    return item_json(item)


RENDERABLE_FORMATS = {"demo", "tips"}
SCENARIO_ROOT = os.environ.get("SCENARIO_ROOT", "./scenarios")


class RenderBody(BaseModel):
    format: str
    scenario: str | None = None


@router.post("/items/{item_id}/render")
def render(item_id: str, body: RenderBody, session: Session = Depends(get_session)):
    item = _get(item_id, session)
    if body.format not in RENDERABLE_FORMATS:
        raise HTTPException(422, f"format must be one of: {', '.join(sorted(RENDERABLE_FORMATS))}")
    if body.format == "demo":
        if not body.scenario:
            raise HTTPException(422, "demo format requires a scenario")
        try:
            load_scenario(body.scenario, SCENARIO_ROOT)
        except ScenarioError as exc:
            raise HTTPException(422, str(exc))
    try:
        transition(item, "rendering")
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    item.format = body.format
    item.scenario = body.scenario
    item.render_error = None
    session.flush()
    get_dispatcher(get_settings()).dispatch(item.id)
    return item_json(item)
