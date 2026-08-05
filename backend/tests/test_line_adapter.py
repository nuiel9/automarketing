import pytest
import respx
from httpx import Response

from app.channels.base import ChannelAuthError, ChannelError, PublishRequest
from app.channels.line import BROADCAST_URL, LineAdapter
from app.config import Settings

SETTINGS = Settings(line_channel_access_token="LTOK")


def req() -> PublishRequest:
    return PublishRequest(
        item_id="i1", channel="line", title=None,
        body="คอร์สใหม่ https://eduverse.one?utm_source=line", media_url=None, state=None,
    )


@respx.mock
def test_broadcast_success():
    route = respx.post(BROADCAST_URL).mock(
        return_value=Response(200, json={}, headers={"x-line-request-id": "rid-1"})
    )
    out = LineAdapter(SETTINGS).publish(req())
    assert out.status == "posted" and out.post_ref == "rid-1"
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer LTOK"
    assert "คอร์สใหม่".encode() in sent.read()


@respx.mock
def test_401_auth_error():
    respx.post(BROADCAST_URL).mock(return_value=Response(401, json={}))
    with pytest.raises(ChannelAuthError):
        LineAdapter(SETTINGS).publish(req())


@respx.mock
def test_429_retryable():
    respx.post(BROADCAST_URL).mock(return_value=Response(429, json={}))
    with pytest.raises(ChannelError):
        LineAdapter(SETTINGS).publish(req())
