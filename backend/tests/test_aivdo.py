import time

import httpx
import pytest
import respx

from app.config import get_settings
from app.video.aivdo import (
    AivdoError,
    ModerationError,
    OutOfCreditsError,
    download,
    generate_ad,
    poll,
)

BASE = "https://aivdo-api-b7iz53omoq-as.a.run.app"
COPY = {"kicker": "k", "name": "n", "tagline": "t", "hl1": "a", "hl2": "b",
        "promo": "p", "cta": "c", "vo_script": "v"}


@pytest.fixture(autouse=True)
def _aivdo_key(monkeypatch):
    # aivdo_api_key defaults to "" and nothing in .env sets it, so generate_ad
    # would send an empty X-API-Key header without this. get_settings() is
    # lru_cache'd (a process-wide singleton shared with the rest of the
    # suite), so this must be monkeypatch.setattr -- not a plain assignment --
    # so it's undone at teardown rather than leaking into other tests.
    monkeypatch.setattr(get_settings(), "aivdo_api_key", "test-key")


@respx.mock
def test_generate_sends_the_configured_style_voice_and_track():
    route = respx.post(f"{BASE}/api/ads/generate").mock(
        return_value=httpx.Response(200, json={
            "job_id": "abc123", "credits_used": 5, "credits_remaining": 329}))

    job_id = generate_ad("data:image/png;base64,AAA", "brief", COPY, "inspiration")

    assert job_id == "abc123"
    body = respx.calls.last.request
    import json
    sent = json.loads(body.content)
    assert sent["style"] == "blueprint"
    assert sent["voice"] == "Charon"
    assert sent["gender"] == "male"
    assert sent["music_track"] == "inspiration"
    assert sent["photos"] == ["data:image/png;base64,AAA"]
    assert sent["copy"] == COPY
    assert body.headers["X-API-Key"]


@respx.mock
def test_out_of_credits_is_its_own_error():
    respx.post(f"{BASE}/api/ads/generate").mock(
        return_value=httpx.Response(402, json={"detail": "Not enough credits. Need 5."}))

    with pytest.raises(OutOfCreditsError):
        generate_ad("data:image/png;base64,AAA", "brief", COPY, None)


@respx.mock
def test_moderation_block_surfaces_aivdos_reason():
    respx.post(f"{BASE}/api/ads/generate").mock(
        return_value=httpx.Response(400, json={"detail": "Content blocked: violence"}))

    with pytest.raises(ModerationError) as exc:
        generate_ad("data:image/png;base64,AAA", "brief", COPY, None)
    assert "violence" in str(exc.value)


@respx.mock
def test_rate_limit_then_success():
    """The endpoint allows 5/minute; a 429 must be retried, not failed."""
    respx.post(f"{BASE}/api/ads/generate").mock(side_effect=[
        httpx.Response(429, json={"detail": "rate limited"}),
        httpx.Response(200, json={"job_id": "ok", "credits_used": 5,
                                  "credits_remaining": 1}),
    ])

    assert generate_ad("data:image/png;base64,AAA", "brief", COPY, None) == "ok"


@respx.mock
def test_read_timeout_is_not_retried_and_raises_immediately():
    """A ReadTimeout can fire AFTER the POST was fully sent, so AIVDO may
    already have created a job and deducted 5 credits before the response
    was lost. Retrying here risks double-dispatch with no job id ever
    persisted -- unrecoverable -- so this must raise after exactly one
    attempt, never retry."""
    route = respx.post(f"{BASE}/api/ads/generate").mock(
        side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(AivdoError):
        generate_ad("data:image/png;base64,AAA", "brief", COPY, None)
    assert route.call_count == 1


@respx.mock
def test_connect_error_is_retried():
    """ConnectError fires before the request reaches AIVDO -- nothing was
    dispatched and nothing was charged, so retrying is safe."""
    respx.post(f"{BASE}/api/ads/generate").mock(side_effect=[
        httpx.ConnectError("connection refused"),
        httpx.Response(200, json={"job_id": "ok2", "credits_used": 5,
                                  "credits_remaining": 100}),
    ])

    assert generate_ad("data:image/png;base64,AAA", "brief", COPY, None) == "ok2"


@respx.mock
def test_other_5xx_is_not_retried():
    """503 is AIVDO's "could not queue; credits refunded" path, so it
    retries. Any other 5xx has no such contract -- the job may already exist
    and 5 credits may already be spent, so retrying risks a second dispatch
    with no job id ever persisted. Exactly one attempt."""
    route = respx.post(f"{BASE}/api/ads/generate").mock(
        return_value=httpx.Response(500, json={"detail": "boom"}))

    with pytest.raises(AivdoError):
        generate_ad("data:image/png;base64,AAA", "brief", COPY, None)
    assert route.call_count == 1


@respx.mock
def test_poll_returns_the_output_url_once_completed():
    respx.get(f"{BASE}/api/jobs/j1").mock(side_effect=[
        httpx.Response(200, json={"status": "queued", "output_url": None}),
        httpx.Response(200, json={"status": "running", "output_url": None}),
        httpx.Response(200, json={"status": "completed",
                                  "output_url": "https://storage.googleapis.com/x.mp4"}),
    ])

    assert poll("j1", timeout=30, interval=0) == "https://storage.googleapis.com/x.mp4"


@respx.mock
@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_terminal_failure_raises_with_aivdos_error_text(status):
    respx.get(f"{BASE}/api/jobs/j2").mock(
        return_value=httpx.Response(200, json={"status": status, "error": "render blew up"}))

    with pytest.raises(AivdoError) as exc:
        poll("j2", timeout=30, interval=0)
    assert "render blew up" in str(exc.value)


@respx.mock
def test_poll_timeout_reports_the_last_status():
    """AIVDO's own sweeper only looks at status == running, so a job that dies
    before that write is never failed on their side. Our timeout is the only
    thing that ends it."""
    respx.get(f"{BASE}/api/jobs/j3").mock(
        return_value=httpx.Response(200, json={"status": "queued",
                                               "current_stage": "Queued"}))

    with pytest.raises(AivdoError) as exc:
        poll("j3", timeout=0, interval=0)
    assert "queued" in str(exc.value)


@respx.mock
def test_poll_survives_a_transient_network_error():
    """A lost response to a status-poll GET must not lose a job whose 5
    credits are already spent -- poll must keep trying, not raise. Deleting
    the except-httpx.HTTPError block in poll leaves this failing."""
    respx.get(f"{BASE}/api/jobs/j4").mock(side_effect=[
        httpx.ReadTimeout("timed out"),
        httpx.Response(200, json={"status": "completed",
                                  "output_url": "https://storage.googleapis.com/y.mp4"}),
    ])

    assert poll("j4", timeout=30, interval=0) == "https://storage.googleapis.com/y.mp4"


@respx.mock
def test_poll_timeout_elapses_across_multiple_iterations():
    """timeout=0 alone doesn't prove the deadline math: a buggy
    `deadline = timeout` (instead of `time.monotonic() + timeout`) also
    raises on the very first check, so it passes test_poll_timeout_reports_
    the_last_status too. Use a real, small, nonzero timeout and measure wall
    clock: a correct deadline must let real time elapse before raising; the
    buggy version raises near-instantly regardless of timeout's value."""
    route = respx.get(f"{BASE}/api/jobs/j5").mock(
        return_value=httpx.Response(200, json={"status": "queued",
                                               "current_stage": "Queued"}))

    start = time.monotonic()
    with pytest.raises(AivdoError):
        poll("j5", timeout=0.05, interval=0)
    assert time.monotonic() - start >= 0.04
    assert route.call_count > 1


@respx.mock
def test_download_fetches_the_signed_url_without_the_api_key():
    """output_url is a GCS v4 signed URL -- sending our key to Google would
    leak it to a third party."""
    route = respx.get("https://storage.googleapis.com/x.mp4").mock(
        return_value=httpx.Response(200, content=b"MP4DATA"))

    assert download("https://storage.googleapis.com/x.mp4") == b"MP4DATA"
    assert "X-API-Key" not in route.calls.last.request.headers
