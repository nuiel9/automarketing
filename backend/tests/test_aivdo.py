import time

import httpx
import pytest
import respx

from app.config import get_settings
from app.video.aivdo import (
    AivdoError,
    AivdoJobDeadError,
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
def test_200_without_a_job_id_raises_and_warns_credits_were_spent():
    """The 5 credits are deducted the instant AIVDO returns 200 -- a body
    that doesn't carry a usable job_id must not raise the bare KeyError a
    naive `body["job_id"]` would, and item.render_error must not end up as
    the string 'job_id'. It must say plainly that credits were probably
    spent and there's no job id to show for it."""
    respx.post(f"{BASE}/api/ads/generate").mock(
        return_value=httpx.Response(200, json={"credits_remaining": 42}))

    with pytest.raises(AivdoError) as exc:
        generate_ad("data:image/png;base64,AAA", "brief", COPY, None)
    # Not a bare KeyError('job_id') -- that's exactly the failure mode this
    # guard exists to prevent (item.render_error would end up as 'job_id').
    assert isinstance(exc.value, AivdoError)
    assert "credit" in str(exc.value).lower()


@respx.mock
def test_200_with_unparseable_body_raises_instead_of_crashing():
    respx.post(f"{BASE}/api/ads/generate").mock(
        return_value=httpx.Response(200, content=b"not json"))

    with pytest.raises(AivdoError) as exc:
        generate_ad("data:image/png;base64,AAA", "brief", COPY, None)
    assert "credit" in str(exc.value).lower()


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
    # Specifically the dead-job subclass -- this is what lets the caller
    # tell "AIVDO confirmed this job is dead" from "we merely gave up
    # watching it" and decide whether clearing the persisted job id is safe.
    assert isinstance(exc.value, AivdoJobDeadError)


@respx.mock
def test_poll_timeout_is_not_a_dead_job_error():
    """A deadline timeout means WE stopped watching, not that AIVDO
    reported the job dead -- it may still be running or may already have
    finished. This must stay a plain AivdoError so a persisted job id
    survives it and a retry can resume rather than pay for a new job."""
    respx.get(f"{BASE}/api/jobs/j2b").mock(
        return_value=httpx.Response(200, json={"status": "queued",
                                               "current_stage": "Queued"}))

    with pytest.raises(AivdoError) as exc:
        poll("j2b", timeout=0, interval=0)
    assert not isinstance(exc.value, AivdoJobDeadError)


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
def test_non_200_poll_response_is_logged(caplog):
    """A non-200 poll response used to update no state and log nothing --
    silent until the deadline. It must at least warn, so an operator
    watching logs during an incident sees AIVDO was misbehaving rather than
    plain silence up to the eventual timeout."""
    respx.get(f"{BASE}/api/jobs/j6").mock(side_effect=[
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"status": "completed",
                                  "output_url": "https://storage.googleapis.com/z.mp4"}),
    ])

    with caplog.at_level("WARNING"):
        result = poll("j6", timeout=30, interval=0)

    assert result == "https://storage.googleapis.com/z.mp4"
    assert any("j6" in r.message and "500" in r.message for r in caplog.records)


@respx.mock
def test_download_fetches_the_signed_url_without_the_api_key():
    """output_url is a GCS v4 signed URL -- sending our key to Google would
    leak it to a third party."""
    route = respx.get("https://storage.googleapis.com/x.mp4").mock(
        return_value=httpx.Response(200, content=b"MP4DATA"))

    assert download("https://storage.googleapis.com/x.mp4") == b"MP4DATA"
    assert "X-API-Key" not in route.calls.last.request.headers
