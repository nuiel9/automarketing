import httpx

from app.channels.base import ChannelAuthError, ChannelError, PublishOutcome, PublishRequest
from app.config import Settings

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"


class LineAdapter:
    def __init__(self, settings: Settings):
        self.token = settings.line_channel_access_token

    def publish(self, req: PublishRequest) -> PublishOutcome:
        resp = httpx.post(
            BROADCAST_URL,
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messages": [{"type": "text", "text": req.body[:4900]}]},
            timeout=30,
        )
        if resp.status_code == 401:
            raise ChannelAuthError("line token invalid")
        if resp.status_code >= 400:
            raise ChannelError(f"line {resp.status_code}: {resp.text[:200]}")
        return PublishOutcome(
            status="posted", post_ref=resp.headers.get("x-line-request-id", "line-ok")
        )
