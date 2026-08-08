import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(20), default="founder_clip")
    topic: Mapped[str] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idea")
    media_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_token: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True, default=lambda: secrets.token_urlsafe(16)
    )
    scenario: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # AIVDO's job id for a motion_ad render. Persisted BEFORE polling starts:
    # credits are spent at dispatch and never refunded afterwards, so a retry
    # must resume this job rather than generate (and pay for) another.
    aivdo_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    render_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    captions: Mapped[list["Caption"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    publications: Mapped[list["Publication"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class Caption(Base):
    __tablename__ = "captions"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"))
    channel: Mapped[str] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False)

    item: Mapped[ContentItem] = relationship(back_populates="captions")


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"))
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    post_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    item: Mapped[ContentItem] = relationship(back_populates="publications")


class ChannelState(Base):
    __tablename__ = "channel_state"

    channel: Mapped[str] = mapped_column(String(20), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto|draft|private|disabled
    needs_reauth: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
