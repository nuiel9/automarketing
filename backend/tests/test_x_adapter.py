import pytest
import respx
from httpx import Response

from app.channels.base import ChannelAuthError, ChannelError, PublishRequest
from app.channels.x import TWEETS_URL, XAdapter
from app.config import Settings

SETTINGS = Settings(
    x_consumer_key="ck", x_consumer_secret="cs",
    x_access_token="at", x_access_token_secret="ats",
)


def req(body="ข้อความ https://eduverse.one?utm_source=x") -> PublishRequest:
    return PublishRequest(
        item_id="i1", channel="x", title=None, body=body, media_url=None, state=None
    )


@respx.mock
def test_posts_tweet_with_oauth1_header():
    route = respx.post(TWEETS_URL).mock(
        return_value=Response(201, json={"data": {"id": "190001"}})
    )
    out = XAdapter(SETTINGS).publish(req())
    assert out.status == "posted" and out.post_ref == "190001"
    assert route.calls[0].request.headers["Authorization"].startswith("OAuth ")


@respx.mock
def test_truncates_over_280_chars_preserving_link():
    long_body = ("ก" * 300) + "\n\nhttps://eduverse.one?utm_source=x"
    route = respx.post(TWEETS_URL).mock(
        return_value=Response(201, json={"data": {"id": "1"}})
    )
    XAdapter(SETTINGS).publish(req(long_body))
    import json
    text = json.loads(route.calls[0].request.read())["text"]
    assert len(text) <= 280
    assert "https://eduverse.one" in text


@respx.mock
def test_401_raises_auth_error():
    respx.post(TWEETS_URL).mock(return_value=Response(401, json={}))
    with pytest.raises(ChannelAuthError):
        XAdapter(SETTINGS).publish(req())


@respx.mock
def test_5xx_raises_retryable():
    respx.post(TWEETS_URL).mock(return_value=Response(503, json={}))
    with pytest.raises(ChannelError):
        XAdapter(SETTINGS).publish(req())
