import os

import pytest

import app.video.tips as tips_mod
from app.strategy import Strategy
from app.video.tips import TipCard, TipSet, TipsError, render_tips, write_tips
from app.video.tts import Narration

STRATEGY = Strategy(voice="v", audiences=["a"], banned_words=[], platform_notes={})
FAKE = TipSet(hook="5 ข้อสอบที่คนพลาด", cards=[
    TipCard(headline="ข้อ 1", body="อ่านโจทย์ให้ครบ"),
    TipCard(headline="ข้อ 2", body="จับเวลาเสมอ"),
])


class FakeModels:
    def __init__(self, text=None, fail=False):
        self.text, self.fail, self.kwargs = text, fail, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise RuntimeError("down")
        return type("R", (), {"text": self.text})()


class FakeClient:
    def __init__(self, text=None, fail=False): self.models = FakeModels(text, fail)


def test_write_tips_uses_structured_output(monkeypatch):
    fake = FakeClient(FAKE.model_dump_json())
    monkeypatch.setattr(tips_mod, "_genai_client", lambda: fake)
    out = write_tips("TGAT", STRATEGY, n=2)
    assert out.hook == "5 ข้อสอบที่คนพลาด"
    assert len(out.cards) == 2
    assert fake.models.kwargs["config"].response_schema is TipSet


def test_write_tips_wraps_errors(monkeypatch):
    monkeypatch.setattr(tips_mod, "_genai_client", lambda: FakeClient(fail=True))
    with pytest.raises(TipsError):
        write_tips("x", STRATEGY)


def test_write_tips_raises_when_zero_cards(monkeypatch):
    empty = TipSet(hook="ไม่มีการ์ด", cards=[])
    fake = FakeClient(empty.model_dump_json())
    monkeypatch.setattr(tips_mod, "_genai_client", lambda: fake)
    with pytest.raises(TipsError):
        write_tips("x", STRATEGY)


def test_card_html_escapes_script_injection():
    card = TipCard(headline="<script>alert(1)</script>", body="ok")
    html_out = tips_mod._card_html(card, 1)
    assert "&lt;script&gt;" in html_out
    assert "<script>alert(1)</script>" not in html_out


@pytest.mark.slow
def test_render_card_with_script_headline_produces_png(tmp_path):
    card = TipCard(headline="<script>alert(1)</script>", body="ok")
    png = str(tmp_path / "card.png")
    tips_mod._card_png(card, 1, png)
    assert os.path.exists(png)
    assert os.path.getsize(png) > 0


@pytest.mark.slow
def test_render_tips_produces_one_segment_per_card(tmp_path, monkeypatch):
    import subprocess

    def _synth(text, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        p = os.path.join(out_dir, f"{abs(hash(text))}.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                        "-i", "sine=frequency=300:duration=1:sample_rate=24000",
                        "-ac", "1", p], capture_output=True, check=True)
        return Narration(text, p, 1.0)

    monkeypatch.setattr(tips_mod, "synthesize", _synth)
    segments = render_tips(FAKE, str(tmp_path))
    assert len(segments) == 2
    for seg in segments:
        assert os.path.exists(seg.clip_path)
        assert seg.fit == "hold"
