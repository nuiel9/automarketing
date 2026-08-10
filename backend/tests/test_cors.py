from fastapi.testclient import TestClient

from app.config import Settings


def _client_allowing(monkeypatch, origins: str) -> TestClient:
    from app import main

    settings = Settings(_env_file=None, frontend_origin=origins)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    return TestClient(main.create_app())


def test_preflight_is_allowed_from_every_configured_origin(monkeypatch):
    # Both of a Cloud Run service's hostnames have to work. Asserting on the
    # echoed allow-origin header rather than on the setting proves the list
    # actually reached the middleware, which is where the bug was.
    client = _client_allowing(monkeypatch, "https://a.example,https://b.example")

    for origin in ("https://a.example", "https://b.example"):
        resp = client.options(
            "/api/items",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == origin, origin


def test_an_unconfigured_origin_is_still_refused(monkeypatch):
    # Widening to a list must not widen to everything -- this is the assertion
    # that would fail if someone "fixed" CORS with allow_origins=["*"].
    client = _client_allowing(monkeypatch, "https://a.example,https://b.example")

    resp = client.options(
        "/api/items",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.headers.get("access-control-allow-origin") is None
