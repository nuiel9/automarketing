import httpx
from authlib.oauth1 import ClientAuth

from app.channels.base import ChannelAuthError, ChannelError, PublishOutcome, PublishRequest
from app.config import Settings

TWEETS_URL = "https://api.x.com/2/tweets"
LIMIT = 280


def _fit(body: str) -> str:
    if len(body) <= LIMIT:
        return body
    lines = body.split("\n\n")
    link = lines[-1] if lines and lines[-1].startswith("http") else ""
    room = LIMIT - (len(link) + 2 if link else 0) - 1
    head = body[: max(room, 0)].rstrip()
    return f"{head}…\n\n{link}" if link else f"{head}…"


class XAdapter:
    def __init__(self, settings: Settings):
        self.auth = ClientAuth(
            client_id=settings.x_consumer_key,
            client_secret=settings.x_consumer_secret,
            token=settings.x_access_token,
            token_secret=settings.x_access_token_secret,
        )

    def publish(self, req: PublishRequest) -> PublishOutcome:
        url, headers, payload = self.auth.prepare("POST", TWEETS_URL, {}, b"")
        resp = httpx.post(
            url, headers=dict(headers), json={"text": _fit(req.body)}, timeout=30
        )
        if resp.status_code in (401, 403):
            raise ChannelAuthError(f"x auth {resp.status_code}")
        if resp.status_code >= 500 or resp.status_code == 429:
            raise ChannelError(f"x {resp.status_code}")
        if resp.status_code >= 400:
            raise ChannelError(f"x {resp.status_code}: {resp.text[:200]}")
        return PublishOutcome(status="posted", post_ref=resp.json()["data"]["id"])
