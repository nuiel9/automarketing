import hashlib
import os
import wave
from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings

SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2


class TTSError(Exception):
    pass


@dataclass
class Narration:
    text: str
    path: str
    seconds: float


@lru_cache
def _client():
    # Cached: a per-call temporary Client can be GC'd mid-request, closing the
    # transport under the in-flight call (same trap fixed in app/captions.py).
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=get_settings().gemini_api_key,
        http_options=types.HttpOptions(timeout=120_000),
    )


def _write_wav(path: str, pcm: bytes) -> float:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)


def synthesize(text: str, out_dir: str) -> Narration:
    os.makedirs(out_dir, exist_ok=True)
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(out_dir, f"{key}.wav")
    if os.path.exists(path):
        with wave.open(path) as w:
            return Narration(text, path, w.getnframes() / w.getframerate())

    settings = get_settings()
    from google.genai import types

    try:
        resp = _client().models.generate_content(
            model=settings.tts_model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=settings.kavee_voice
                        )
                    )
                ),
            ),
        )
        pcm = resp.candidates[0].content.parts[0].inline_data.data
    except Exception as exc:
        raise TTSError(str(exc)) from exc

    if not pcm:
        raise TTSError("tts returned no audio")
    return Narration(text, path, _write_wav(path, pcm))
