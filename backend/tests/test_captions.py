import pytest

import app.captions as captions
from app.captions import CaptionError, CaptionSet, ChannelCaption, write_captions
from app.config import get_settings
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


def _set_provider(monkeypatch, provider: str) -> None:
    monkeypatch.setattr(get_settings(), "caption_provider", provider)


# --- anthropic provider ---


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


def test_anthropic_write_captions_returns_set(monkeypatch):
    _set_provider(monkeypatch, "anthropic")
    fake = FakeClient()
    monkeypatch.setattr(captions, "_client", lambda: fake)
    result = write_captions("TGAT คณิต", "hook", STRATEGY)
    assert result.tiktok.hashtags == ["#DEK69"]
    assert fake.messages.kwargs["model"] == "claude-opus-5"
    assert fake.messages.kwargs["output_format"] is CaptionSet
    assert "TGAT คณิต" in fake.messages.kwargs["messages"][0]["content"]


def test_anthropic_write_captions_wraps_errors(monkeypatch):
    _set_provider(monkeypatch, "anthropic")
    monkeypatch.setattr(captions, "_client", lambda: FakeClient(fail=True))
    with pytest.raises(CaptionError):
        write_captions("t", None, STRATEGY)


# --- gemini provider (default) ---


class FakeGenaiResponse:
    def __init__(self, text: str | None):
        self.text = text


class FakeGenaiModels:
    def __init__(self, text: str | None, fail: bool = False):
        self.text = text
        self.fail = fail
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise RuntimeError("api down")
        return FakeGenaiResponse(self.text)


class FakeGenaiClient:
    def __init__(self, text: str | None, fail: bool = False):
        self.models = FakeGenaiModels(text, fail)


def test_gemini_is_default_provider():
    assert get_settings().caption_provider == "gemini"


def test_gemini_write_captions_returns_set(monkeypatch):
    _set_provider(monkeypatch, "gemini")
    fake = FakeGenaiClient(FAKE.model_dump_json())
    monkeypatch.setattr(captions, "_genai_client", lambda: fake)
    result = write_captions("TGAT คณิต", "hook", STRATEGY)
    assert result.tiktok.hashtags == ["#DEK69"]
    assert fake.models.kwargs["model"] == get_settings().gemini_model
    assert fake.models.kwargs["config"].response_schema is CaptionSet
    assert "TGAT คณิต" in fake.models.kwargs["contents"]
    assert "Kavee" in fake.models.kwargs["config"].system_instruction


def test_gemini_wraps_api_errors(monkeypatch):
    _set_provider(monkeypatch, "gemini")
    monkeypatch.setattr(captions, "_genai_client", lambda: FakeGenaiClient(None, fail=True))
    with pytest.raises(CaptionError):
        write_captions("t", None, STRATEGY)


def test_gemini_empty_text_raises(monkeypatch):
    _set_provider(monkeypatch, "gemini")
    monkeypatch.setattr(captions, "_genai_client", lambda: FakeGenaiClient(""))
    with pytest.raises(CaptionError):
        write_captions("t", None, STRATEGY)


def test_gemini_malformed_json_raises(monkeypatch):
    _set_provider(monkeypatch, "gemini")
    monkeypatch.setattr(captions, "_genai_client", lambda: FakeGenaiClient("not json"))
    with pytest.raises(CaptionError):
        write_captions("t", None, STRATEGY)


def test_unknown_provider_raises(monkeypatch):
    _set_provider(monkeypatch, "azure")
    with pytest.raises(CaptionError):
        write_captions("t", None, STRATEGY)
