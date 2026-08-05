import anthropic
from pydantic import BaseModel

from app.config import get_settings
from app.strategy import Strategy


class ChannelCaption(BaseModel):
    title: str | None = None
    body: str
    hashtags: list[str] = []


class CaptionSet(BaseModel):
    tiktok: ChannelCaption
    youtube: ChannelCaption
    instagram: ChannelCaption
    facebook: ChannelCaption
    x: ChannelCaption
    line: ChannelCaption


class CaptionError(Exception):
    pass


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


SYSTEM_TEMPLATE = """You write Thai social media copy for Eduverse One,
an AI tutor app where users type a goal or drop a PDF and get a full course
with a Thai voice tutor named Kavee.

Brand voice: {voice}
Audiences: {audiences}
Per-platform notes: {notes}

Rules: natural Thai a real person would post, no hard selling, no invented
features or guarantees. Do NOT include URLs — links are appended by the system.
X body must be under 250 characters. YouTube needs a searchable title."""


def write_captions(topic: str, hook: str | None, strategy: Strategy) -> CaptionSet:
    system = SYSTEM_TEMPLATE.format(
        voice=strategy.voice,
        audiences=", ".join(strategy.audiences),
        notes="; ".join(f"{k}: {v}" for k, v in strategy.platform_notes.items()),
    )
    user = f"Topic: {topic}\nHook: {hook or '-'}\nWrite captions for all six channels."
    try:
        response = _client().messages.parse(
            model="claude-opus-5",
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=CaptionSet,
        )
    except Exception as exc:
        raise CaptionError(str(exc)) from exc
    if response.parsed_output is None:
        raise CaptionError("model returned no parsed output")
    return response.parsed_output
