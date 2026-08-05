import os
import struct
import wave

import pytest

import app.video.tts as tts
from app.video.tts import TTSError, synthesize


def _pcm(seconds: float = 0.5, rate: int = 24_000) -> bytes:
    return struct.pack("<h", 0) * int(rate * seconds)


class FakePart:
    def __init__(self, data): self.inline_data = type("D", (), {"data": data})()


class FakeModels:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls = data, fail, 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("tts down")
        self.kwargs = kwargs
        cand = type("C", (), {"content": type("X", (), {"parts": [FakePart(self.data)]})()})()
        return type("R", (), {"candidates": [cand]})()


class FakeClient:
    def __init__(self, data=None, fail=False): self.models = FakeModels(data, fail)


def test_synthesize_writes_wav_and_measures_duration(tmp_path, monkeypatch):
    fake = FakeClient(_pcm(0.5))
    monkeypatch.setattr(tts, "_client", lambda: fake)
    n = synthesize("สวัสดีครับ", str(tmp_path))
    assert os.path.exists(n.path)
    assert 0.45 < n.seconds < 0.55
    with wave.open(n.path) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 24_000
    assert fake.models.kwargs["model"] == "gemini-3.1-flash-tts-preview"
    voice_config = fake.models.kwargs["config"].speech_config.voice_config
    assert voice_config.prebuilt_voice_config.voice_name == "Charon"


def test_client_is_lru_cached():
    assert hasattr(tts._client, "cache_info")


def test_synthesize_is_cached_by_text(tmp_path, monkeypatch):
    fake = FakeClient(_pcm(0.3))
    monkeypatch.setattr(tts, "_client", lambda: fake)
    a = synthesize("ซ้ำ", str(tmp_path))
    b = synthesize("ซ้ำ", str(tmp_path))
    assert a.path == b.path
    assert fake.models.calls == 1          # second call served from disk


def test_api_failure_raises_tts_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "_client", lambda: FakeClient(fail=True))
    with pytest.raises(TTSError):
        synthesize("x", str(tmp_path))


def test_empty_audio_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "_client", lambda: FakeClient(b""))
    with pytest.raises(TTSError):
        synthesize("x", str(tmp_path))
