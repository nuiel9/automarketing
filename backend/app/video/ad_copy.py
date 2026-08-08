"""Thai ad copy for a Motion Ad, in Eduverse's brand voice.

AIVDO's /api/ads/generate renders "the PRE-APPROVED style+copy directly (no
re-analyze)" -- the copy sent is the copy that ships. So OUR voice and OUR
banned-words list stay authoritative, and the gate can run before any credits
are spent. (AIVDO has its own Gemini copywriter behind a different endpoint;
we do not call it.)
"""

from functools import lru_cache

from pydantic import BaseModel

from app.config import get_settings
from app.strategy import Strategy, banned_violations

# AIVDO's own caps (aivdo/modules/motion_ad_api.py _COPY_CAP). Applied here so
# the copy we send is the copy that renders, rather than being silently
# truncated on their side.
_CAPS = {
    "kicker": 120, "name": 120, "tagline": 120, "hl1": 120,
    "hl2": 120, "promo": 120, "cta": 120, "vo_script": 160,
}


class AdCopyError(Exception):
    pass


class BannedCopyError(AdCopyError):
    def __init__(self, words: list[str]):
        super().__init__(f"ad copy contains banned words: {', '.join(words)}")
        self.words = words


class AdCopy(BaseModel):
    kicker: str
    name: str
    tagline: str
    hl1: str
    hl2: str
    promo: str
    cta: str
    vo_script: str

    def as_payload(self) -> dict:
        """The `copy` object for POST /api/ads/generate, capped per field."""
        return {f: getattr(self, f)[:cap] for f, cap in _CAPS.items()}


@lru_cache
def _genai_client():
    # Cached: a per-call temporary Client can be GC'd mid-request, closing the
    # transport under the in-flight call (same trap fixed in captions.py/tips.py).
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=get_settings().gemini_api_key,
        http_options=types.HttpOptions(timeout=120_000),
    )


def write_ad_copy(topic: str, strategy: Strategy) -> AdCopy:
    from google.genai import types

    system = (
        "You write Thai copy for an 11-second vertical video ad for Eduverse "
        "One, an AI tutor app.\n"
        f"Brand voice: {strategy.voice}\n"
        f"Audiences: {', '.join(strategy.audiences)}\n"
        "Fields: kicker (short category line), name (the brand name, "
        "'Eduverse One'), tagline (one-line promise), hl1 and hl2 (two benefit "
        "lines), promo (an offer line), cta (action plus destination), "
        "vo_script (the spoken voiceover).\n"
        "Every line must be short enough to read on a phone screen. "
        "vo_script must read aloud in about 8 seconds -- keep it UNDER 110 "
        "Thai characters, lead with the hook, finish with the call to action, "
        "spell numbers as Thai words, and use no emoji.\n"
        "No URLs other than eduverse.one, no invented statistics, no guarantees."
    )
    try:
        resp = _genai_client().models.generate_content(
            model=get_settings().tips_model,
            contents=f"หัวข้อ: {topic}",
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=AdCopy,
                max_output_tokens=2048,
            ),
        )
    except Exception as exc:
        raise AdCopyError(str(exc)) from exc
    if not resp.text:
        raise AdCopyError("ad copy model returned no output")
    try:
        copy = AdCopy.model_validate_json(resp.text)
    except Exception as exc:
        raise AdCopyError(f"invalid ad copy payload: {exc}") from exc

    # Gate BEFORE the caller spends 5 credits. Checked against the capped
    # payload, since that is the text that actually renders.
    violations = banned_violations(strategy, list(copy.as_payload().values()))
    if violations:
        raise BannedCopyError(violations)
    return copy
