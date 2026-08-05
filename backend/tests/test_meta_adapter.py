import pytest
import respx
from httpx import Response

from app.channels.base import ChannelAuthError, ChannelError, PublishRequest
from app.channels.meta import GRAPH, MetaAdapter
from app.config import Settings

SETTINGS = Settings(
    meta_page_id="PAGE", meta_ig_user_id="IGU", meta_access_token="TOK"
)


def req(channel: str, state=None) -> PublishRequest:
    return PublishRequest(
        item_id="i1", channel=channel, title=None, body="แคปชัน",
        media_url="https://app.example/media/tok1", state=state,
    )


@respx.mock
def test_facebook_video_post():
    route = respx.post(f"{GRAPH}/PAGE/videos").mock(
        return_value=Response(200, json={"id": "fb123"})
    )
    out = MetaAdapter(SETTINGS).publish(req("facebook"))
    assert out.status == "posted" and out.post_ref == "fb123"
    sent = route.calls[0].request
    assert b"file_url" in sent.read() and b"TOK" in sent.read()


@respx.mock
def test_instagram_phase1_creates_container():
    respx.post(f"{GRAPH}/IGU/media").mock(
        return_value=Response(200, json={"id": "c77"})
    )
    out = MetaAdapter(SETTINGS).publish(req("instagram"))
    assert out.status == "pending" and out.state == {"creation_id": "c77"}


@respx.mock
def test_instagram_phase2_finished_publishes():
    respx.get(f"{GRAPH}/c77").mock(
        return_value=Response(200, json={"status_code": "FINISHED"})
    )
    respx.post(f"{GRAPH}/IGU/media_publish").mock(
        return_value=Response(200, json={"id": "ig900"})
    )
    out = MetaAdapter(SETTINGS).publish(req("instagram", state={"creation_id": "c77"}))
    assert out.status == "posted" and out.post_ref == "ig900"


@respx.mock
def test_instagram_phase2_in_progress_stays_pending():
    respx.get(f"{GRAPH}/c77").mock(
        return_value=Response(200, json={"status_code": "IN_PROGRESS"})
    )
    out = MetaAdapter(SETTINGS).publish(req("instagram", state={"creation_id": "c77"}))
    assert out.status == "pending" and out.state == {"creation_id": "c77"}


@respx.mock
def test_expired_token_raises_auth_error():
    respx.post(f"{GRAPH}/PAGE/videos").mock(
        return_value=Response(400, json={"error": {"code": 190, "message": "expired"}})
    )
    with pytest.raises(ChannelAuthError):
        MetaAdapter(SETTINGS).publish(req("facebook"))


@respx.mock
def test_server_error_raises_retryable():
    respx.post(f"{GRAPH}/PAGE/videos").mock(return_value=Response(500, json={}))
    with pytest.raises(ChannelError):
        MetaAdapter(SETTINGS).publish(req("facebook"))


@respx.mock
def test_instagram_phase2_error_status_raises_channel_error():
    respx.get(f"{GRAPH}/c77").mock(
        return_value=Response(200, json={"status_code": "ERROR"})
    )
    with pytest.raises(ChannelError):
        MetaAdapter(SETTINGS).publish(req("instagram", state={"creation_id": "c77"}))


@respx.mock
def test_other_4xx_raises_channel_error_not_auth_error():
    respx.post(f"{GRAPH}/PAGE/videos").mock(
        return_value=Response(400, json={"error": {"code": 100, "message": "bad file_url"}})
    )
    with pytest.raises(ChannelError) as exc_info:
        MetaAdapter(SETTINGS).publish(req("facebook"))
    assert not isinstance(exc_info.value, ChannelAuthError)
    assert "bad file_url" in str(exc_info.value)
