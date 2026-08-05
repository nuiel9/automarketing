from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass
class PublishRequest:
    item_id: str
    channel: str
    title: str | None
    body: str            # final text incl. UTM link, hashtags appended
    media_url: str | None
    state: dict | None   # prior external state (pending_external), else None


@dataclass
class PublishOutcome:
    status: Literal["posted", "pending"]
    post_ref: str | None = None
    state: dict | None = None


class ChannelError(Exception):        # retryable
    pass


class ChannelAuthError(ChannelError):  # pauses channel
    pass


class ChannelAdapter(Protocol):
    def publish(self, req: PublishRequest) -> PublishOutcome: ...
