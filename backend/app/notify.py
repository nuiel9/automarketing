import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


def line_notify(text: str) -> None:
    settings = get_settings()
    if not (settings.line_channel_access_token and settings.line_founder_user_id):
        log.warning("notify (no LINE configured): %s", text)
        return
    try:
        httpx.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {settings.line_channel_access_token}"},
            json={"to": settings.line_founder_user_id,
                  "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=10,
        )
    except Exception:
        # A failed alert must never take down the caller (a publisher tick).
        log.exception("line_notify failed to send: %s", text)
