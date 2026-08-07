import html
import os
from functools import lru_cache

from pydantic import BaseModel

from app.config import get_settings
from app.strategy import Strategy
from app.video.compose import Segment
from app.video.ffmpeg import run
from app.video.tts import synthesize

CARD_W, CARD_H = 540, 960


class TipsError(Exception):
    pass


class TipCard(BaseModel):
    headline: str
    body: str


class TipSet(BaseModel):
    hook: str
    cards: list[TipCard]


@lru_cache
def _genai_client():
    # Cached: a per-call temporary Client can be GC'd mid-request, closing
    # the transport under the in-flight call (same trap fixed in app/tts.py
    # and app/captions.py).
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=get_settings().gemini_api_key,
        http_options=types.HttpOptions(timeout=120_000),
    )


def write_tips(topic: str, strategy: Strategy, n: int = 5) -> TipSet:
    from google.genai import types

    system = (
        "You write short Thai tips-card content for Eduverse One, an AI tutor app.\n"
        f"Brand voice: {strategy.voice}\n"
        f"Audiences: {', '.join(strategy.audiences)}\n"
        f"Write exactly {n} cards. Each headline is at most 6 Thai words; each body is "
        "one sentence a student can act on. Plus one hook line for the video opening. "
        "No URLs, no invented statistics, no guarantees."
    )
    try:
        resp = _genai_client().models.generate_content(
            model=get_settings().tips_model,
            contents=f"หัวข้อ: {topic}",
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=TipSet,
                max_output_tokens=4096,
            ),
        )
    except Exception as exc:
        raise TipsError(str(exc)) from exc
    if not resp.text:
        raise TipsError("tips model returned no output")
    try:
        tips = TipSet.model_validate_json(resp.text)
    except Exception as exc:
        raise TipsError(f"invalid tips payload: {exc}") from exc
    if not tips.cards:
        # Otherwise render_tips() silently returns [] and ffmpeg fails deep
        # inside compose() on an empty concat list -- a confusing failure
        # far from its cause. Fail fast, right where the model's output is
        # actually inspected.
        raise TipsError("tips model returned zero cards")
    return tips


# Verified on this Mac with Chromium's CSS.getPlatformFontsForNode: this
# chain, the plain 'Noto Sans Thai',sans-serif the brief originally
# specified, and even a deliberately bogus family name all resolved Thai
# text to Thonburi identically -- macOS falls back to a script-appropriate
# system font (Thonburi) regardless of what's listed in font-family, once
# nothing in the list is actually installed ("Noto Sans Thai" isn't, here).
# So the explicit 'Thonburi','Ayuthaya' entries are not doing anything
# provably useful on macOS; they're kept anyway because they're harmless
# and may matter on Linux, where fontconfig (not a script-fallback engine)
# governs resolution. The render image (render/Dockerfile, Task 11) is
# Ubuntu 22.04 "jammy" (mcr.microsoft.com/playwright/python:v1.49.0-jammy)
# with `fonts-noto-core` installed via apt, which is expected to register
# "Noto Sans Thai" with fontconfig there -- but that path is UNVERIFIED
# until Task 11's Dockerfile exists; only the macOS behaviour above has
# actually been tested.
_CARD_HTML = """<!doctype html><meta charset="utf-8">
<style>
 body{{margin:0;width:{w}px;height:{h}px;background:#0F172A;color:#F8FAFC;
   font-family:'Noto Sans Thai','Thonburi','Ayuthaya',sans-serif;display:flex;flex-direction:column;
   justify-content:center;padding:64px;box-sizing:border-box}}
 .n{{font-size:28px;color:#F59E0B;letter-spacing:4px;margin-bottom:24px}}
 h1{{font-size:64px;line-height:1.2;margin:0 0 32px}}
 p{{font-size:40px;line-height:1.5;margin:0;color:#CBD5E1}}
</style>
<div class="n">{index}</div><h1>{headline}</h1><p>{body}</p>"""


def _card_html(card: TipCard, index: int) -> str:
    # headline/body are Gemini output, i.e. untrusted text -- escape before
    # interpolating into HTML so it can never break out of its element (a
    # reviewer reproduced `</h1><script>...</script>` executing here before
    # this fix). Belt-and-suspenders with java_script_enabled=False below:
    # this card is loaded in a --no-sandbox Chromium that, in Task 11, runs
    # in Cloud Run where the metadata server is reachable, so script
    # execution in this context is a credential-exfiltration surface, not a
    # cosmetic bug.
    return _CARD_HTML.format(
        w=CARD_W, h=CARD_H, index=f"{index:02d}",
        headline=html.escape(card.headline), body=html.escape(card.body),
    )


def _card_png(card: TipCard, index: int, path: str) -> None:
    from playwright.sync_api import sync_playwright

    page_html = _card_html(card, index)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_context(
            viewport={"width": CARD_W, "height": CARD_H}, device_scale_factor=2,
            java_script_enabled=False,
        ).new_page()
        page.set_content(page_html)
        page.screenshot(path=path)
        browser.close()


def render_tips(tips: TipSet, work_dir: str) -> list[Segment]:
    os.makedirs(work_dir, exist_ok=True)
    audio_dir = os.path.join(work_dir, "audio")
    segments = []
    for index, card in enumerate(tips.cards, start=1):
        narration = synthesize(f"{card.headline} {card.body}", audio_dir)
        png = os.path.join(work_dir, f"card_{index}.png")
        _card_png(card, index, png)
        clip = os.path.join(work_dir, f"card_{index}.mp4")
        # slow Ken Burns push so a static card still feels alive
        run(["ffmpeg", "-y", "-loop", "1", "-i", png, "-t", f"{narration.seconds}",
             "-vf", f"scale=2160:3840,zoompan=z='min(zoom+0.0006,1.10)':"
                    f"d={int(narration.seconds * 30)}:s=1080x1920:fps=30",
             "-pix_fmt", "yuv420p", clip])
        segments.append(Segment(clip, narration, fit="hold", sound=None))
    return segments
