from app.config import get_settings
from app.notify import line_notify


def test_line_notify_swallows_httpx_errors(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "line_channel_access_token", "tok")
    monkeypatch.setattr(settings, "line_founder_user_id", "U123")

    def boom(*args, **kwargs):
        raise RuntimeError("network is down")

    import app.notify as notify_mod

    monkeypatch.setattr(notify_mod.httpx, "post", boom)

    # Must not raise: a failed alert must never kill the caller (a tick).
    line_notify("hello")
