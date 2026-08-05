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


def _genai_client():
    # Lazy import: environments running the anthropic provider don't need the SDK.
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=get_settings().gemini_api_key,
        http_options=types.HttpOptions(timeout=120_000),  # ms
    )


SYSTEM_TEMPLATE = """You write Thai social media copy for Eduverse One,
an AI tutor app where users type a goal or drop a PDF and get a full course
with a Thai voice tutor named Kavee.

Brand voice: {voice}
Audiences: {audiences}
Per-platform notes: {notes}

Rules: natural Thai a real person would post, no hard selling, no invented
features or guarantees. Do NOT include URLs — links are appended by the system.
X body must be under 250 characters. YouTube needs a searchable title."""


def _build_prompts(topic: str, hook: str | None, strategy: Strategy) -> tuple[str, str]:
    system = SYSTEM_TEMPLATE.format(
        voice=strategy.voice,
        audiences=", ".join(strategy.audiences),
        notes="; ".join(f"{k}: {v}" for k, v in strategy.platform_notes.items()),
    )
    user = f"Topic: {topic}\nHook: {hook or '-'}\nWrite captions for all six channels."
    return system, user


def _write_anthropic(system: str, user: str) -> CaptionSet:
    response = _client().messages.parse(
        model="claude-opus-5",
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=CaptionSet,
    )
    if response.parsed_output is None:
        raise CaptionError("model returned no parsed output")
    return response.parsed_output


def _write_gemini(system: str, user: str) -> CaptionSet:
    from google.genai import types

    response = _genai_client().models.generate_content(
        model=get_settings().gemini_model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=CaptionSet,
            max_output_tokens=8192,
        ),
    )
    if not response.text:
        raise CaptionError("model returned no output")
    return CaptionSet.model_validate_json(response.text)


def write_captions(topic: str, hook: str | None, strategy: Strategy) -> CaptionSet:
    system, user = _build_prompts(topic, hook, strategy)
    provider = get_settings().caption_provider
    try:
        if provider == "anthropic":
            return _write_anthropic(system, user)
        if provider == "gemini":
            return _write_gemini(system, user)
    except CaptionError:
        raise
    except Exception as exc:
        raise CaptionError(str(exc)) from exc
    raise CaptionError(f"unknown caption provider: {provider}")
