import pytest

from app.strategy import Strategy
from app.video.ad_copy import AdCopy, AdCopyError, BannedCopyError, write_ad_copy

STRATEGY = Strategy(
    voice="เป็นกันเอง จริงใจ",
    audiences=["นักเรียนเตรียมสอบ"],
    banned_words=["รับประกันสอบติด"],
    platform_notes={},
)

GOOD = AdCopy(
    kicker="ติวเตอร์ AI ภาษาไทย", name="Eduverse One",
    tagline="บอกหัวข้อที่อยากเรียน แล้วได้คอร์สทันที",
    hl1="คอร์สเฉพาะคุณใน 2 นาที", hl2="มีพี่กวีสอนด้วยเสียง",
    promo="เริ่มเรียนฟรี", cta="เริ่มที่ eduverse.one",
    vo_script="อยากเรียนอะไร บอกพี่กวีได้เลยครับ",
)


def _stub_model(monkeypatch, copy: AdCopy):
    import app.video.ad_copy as mod

    class _Resp:
        text = copy.model_dump_json()

    class _Models:
        def generate_content(self, **kw):
            return _Resp()

    monkeypatch.setattr(mod, "_genai_client", lambda: type("C", (), {"models": _Models()})())


def test_all_eight_fields_are_capped_to_aivdo_limits():
    """AIVDO truncates silently via cap_copy; we cap so the copy we send is
    the copy that renders."""
    long = AdCopy(**{f: "ก" * 400 for f in AdCopy.model_fields})
    payload = long.as_payload()

    for field in ("kicker", "name", "tagline", "hl1", "hl2", "promo", "cta"):
        assert len(payload[field]) == 120
    assert len(payload["vo_script"]) == 160


def test_write_ad_copy_returns_all_eight_fields(monkeypatch):
    _stub_model(monkeypatch, GOOD)
    copy = write_ad_copy("เทคนิคจำศัพท์", STRATEGY)
    assert set(copy.as_payload()) == {
        "kicker", "name", "tagline", "hl1", "hl2", "promo", "cta", "vo_script",
    }
    assert copy.name == "Eduverse One"


def test_banned_words_raise_before_any_credit_is_spent(monkeypatch):
    """The gate exists so a brand-voice violation costs zero credits.

    This is only possible because /api/ads/generate renders pre-approved copy
    without re-analyzing it -- the copy we send is the copy that ships.
    """
    bad = GOOD.model_copy(update={"promo": "รับประกันสอบติด 100%"})
    _stub_model(monkeypatch, bad)

    with pytest.raises(BannedCopyError) as exc:
        write_ad_copy("เทคนิคจำศัพท์", STRATEGY)
    assert "รับประกันสอบติด" in exc.value.words


def test_banned_word_past_the_cap_does_not_raise(monkeypatch):
    """Complement of test_banned_words_raise_before_any_credit_is_spent: a
    banned word placed entirely past the 120-char cap never renders, so the
    gate -- checked against the CAPPED payload -- must let it through.

    This is the test that actually discriminates "gate on capped text" from
    "gate on raw text": the banned word here sits outside the clean 120-char
    prefix, so gating on raw fields (the bug this task guards against) would
    raise here, while gating on the capped payload (the correct behaviour)
    must not.
    """
    banned = STRATEGY.banned_words[0]
    clean_prefix = "ก" * 120
    hidden = GOOD.model_copy(update={"promo": clean_prefix + banned})
    _stub_model(monkeypatch, hidden)

    copy = write_ad_copy("เทคนิคจำศัพท์", STRATEGY)
    assert copy.as_payload()["promo"] == clean_prefix
    assert banned not in copy.as_payload()["promo"]


def test_model_returning_nothing_raises(monkeypatch):
    import app.video.ad_copy as mod

    class _Resp:
        text = ""

    class _Models:
        def generate_content(self, **kw):
            return _Resp()

    monkeypatch.setattr(mod, "_genai_client", lambda: type("C", (), {"models": _Models()})())
    with pytest.raises(AdCopyError):
        write_ad_copy("เทคนิคจำศัพท์", STRATEGY)
