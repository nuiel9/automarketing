import pytest

import app.captions as captions
from app.captions import CaptionError, CaptionSet, ChannelCaption, write_captions
from app.strategy import Strategy

STRATEGY = Strategy(voice="v", audiences=["a"], banned_words=[], platform_notes={})

FAKE = CaptionSet(
    tiktok=ChannelCaption(title=None, body="ติวสอบ", hashtags=["#DEK69"]),
    youtube=ChannelCaption(title="ติว TGAT", body="รายละเอียด", hashtags=[]),
    instagram=ChannelCaption(title=None, body="ig", hashtags=[]),
    facebook=ChannelCaption(title=None, body="fb", hashtags=[]),
    x=ChannelCaption(title=None, body="x", hashtags=[]),
    line=ChannelCaption(title=None, body="line", hashtags=[]),
)


class FakeParsed:
    parsed_output = FAKE


class FakeMessages:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise RuntimeError("api down")
        return FakeParsed()


class FakeClient:
    def __init__(self, fail: bool = False):
        self.messages = FakeMessages(fail)


def test_write_captions_returns_set(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(captions, "_client", lambda: fake)
    result = write_captions("TGAT คณิต", "hook", STRATEGY)
    assert result.tiktok.hashtags == ["#DEK69"]
    assert fake.messages.kwargs["model"] == "claude-opus-5"
    assert fake.messages.kwargs["output_format"] is CaptionSet
    assert "TGAT คณิต" in fake.messages.kwargs["messages"][0]["content"]


def test_write_captions_wraps_errors(monkeypatch):
    monkeypatch.setattr(captions, "_client", lambda: FakeClient(fail=True))
    with pytest.raises(CaptionError):
        write_captions("t", None, STRATEGY)
