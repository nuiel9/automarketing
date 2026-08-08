"""Client for AIVDO's Motion Ad API.

Auth is `X-API-Key`: AIVDO's get_current_user accepts a key in place of a JWT
and require_verified_email chains off it, so a key alone is enough to
generate.

Credits are deducted at dispatch and refunded ONLY if dispatch itself fails.
Once generate_ad returns a job id, those 5 credits are spent no matter what
happens next -- which is why the caller persists the id and resumes polling
instead of generating again.
"""

import logging
import time

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_TERMINAL_OK = "completed"
_TERMINAL_BAD = {"failed", "canceled"}


class AivdoError(Exception):
    pass


class OutOfCreditsError(AivdoError):
    pass


class ModerationError(AivdoError):
    pass


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", resp.text))[:300]
    except Exception:
        return resp.text[:300]


def generate_ad(photo_data_uri: str, brief: str, copy: dict,
                track_id: str | None) -> str:
    """Dispatch an ad render. Returns the AIVDO job id.

    THE CALLER MUST PERSIST THE RETURNED ID BEFORE POLLING. The 5 credits are
    already spent by the time this returns.
    """
    settings = get_settings()
    payload = {
        "photos": [photo_data_uri],
        "brief": brief[:400],
        "style": settings.aivdo_style,
        "copy": copy,
        "voice": settings.aivdo_voice,
        # Matches Charon's registry gender, so AIVDO's Thai particle
        # correction produces ครับ rather than ค่ะ.
        "gender": "male",
    }
    if track_id:
        payload["music_track"] = track_id

    # Retrying dispatch is only safe when we can be confident AIVDO never
    # processed the request. ConnectError/ConnectTimeout fire before the POST
    # reaches the server, so nothing was created and nothing was charged.
    # 429 (rate limit) and 503 are also safe: AIVDO returns 503 specifically
    # from its "could not queue ads job; credits refunded" path. Anything
    # else -- notably ReadTimeout, and any 5xx other than 503 -- can happen
    # AFTER the POST was fully sent, meaning AIVDO may already have created
    # the job and deducted 5 credits before we lost the response. Retrying
    # those risks double (or quadruple) dispatch with no job id ever
    # persisted, which is unrecoverable -- so those raise immediately
    # instead of retrying. This deliberately narrows the naive "5xx ->
    # retry" rule to 503 only.
    _RETRYABLE_STATUS = {429, 503}

    for attempt in range(4):
        try:
            resp = httpx.post(
                f"{settings.aivdo_base_url}/api/ads/generate",
                json=payload,
                headers={"X-API-Key": settings.aivdo_api_key},
                timeout=120,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if attempt == 3:
                raise AivdoError(f"could not reach AIVDO: {exc}") from exc
            time.sleep(2 ** attempt)
            continue
        except httpx.HTTPError as exc:
            # e.g. ReadTimeout, WriteError, RemoteProtocolError: the request
            # may have been fully sent, so a job may already exist and
            # credits may already be spent. Do not retry -- surface it so an
            # operator can check AIVDO before running this again.
            raise AivdoError(
                f"AIVDO dispatch request failed after it may have reached "
                f"the server -- a job may already exist and 5 credits may "
                f"already be spent; check AIVDO before retrying: {exc}"
            ) from exc
        if resp.status_code == 200:
            body = resp.json()
            # The only visibility we get into the budget.
            log.info("motion_ad dispatched job=%s credits_remaining=%s",
                     body.get("job_id"), body.get("credits_remaining"))
            return body["job_id"]
        if resp.status_code == 402:
            raise OutOfCreditsError(f"AIVDO is out of credits: {_detail(resp)}")
        if resp.status_code == 400:
            # AIVDO moderates BEFORE deducting, so this costs nothing.
            raise ModerationError(f"AIVDO rejected the ad copy: {_detail(resp)}")
        if resp.status_code in _RETRYABLE_STATUS:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise AivdoError(
                f"AIVDO returned {resp.status_code} after retries: {_detail(resp)}")
        if resp.status_code >= 500:
            # Unlike 503, other 5xx codes have no known refund contract --
            # we don't know whether the job was created and credits spent.
            raise AivdoError(
                f"AIVDO returned {resp.status_code}; a job may already exist "
                f"and credits may already be spent; check AIVDO before "
                f"retrying: {_detail(resp)}")
        raise AivdoError(f"AIVDO returned {resp.status_code}: {_detail(resp)}")


def poll(job_id: str, timeout: int, interval: float = 10.0) -> str:
    """Poll until the job finishes; return its output_url.

    Never relies on AIVDO to fail a stuck job: their sweep_stalled_jobs
    selects only `status == "running"`, so a job that dies before that write
    sits at "queued" forever. This timeout is what ends it on our side.
    """
    settings = get_settings()
    deadline = time.monotonic() + timeout
    status, stage = "unknown", ""
    while True:
        try:
            resp = httpx.get(
                f"{settings.aivdo_base_url}/api/jobs/{job_id}",
                headers={"X-API-Key": settings.aivdo_api_key},
                timeout=60,
            )
            if resp.status_code == 200:
                body = resp.json()
                status = body.get("status", "unknown")
                stage = body.get("current_stage") or ""
                if status == _TERMINAL_OK:
                    url = body.get("output_url")
                    if not url:
                        raise AivdoError(
                            f"job {job_id} completed without an output_url")
                    return url
                if status in _TERMINAL_BAD:
                    raise AivdoError(
                        f"AIVDO job {job_id} {status}: {body.get('error') or 'no reason given'}")
        except httpx.HTTPError as exc:
            # A transient polling error must not lose a job whose credits are
            # already spent -- keep polling until the deadline.
            log.warning("polling AIVDO job %s failed: %s", job_id, exc)
        if time.monotonic() >= deadline:
            raise AivdoError(
                f"AIVDO job {job_id} did not finish within {timeout}s "
                f"(last status={status!r} stage={stage!r})")
        time.sleep(interval)


def download(url: str) -> bytes:
    """Fetch the finished MP4 from its GCS v4 signed URL.

    No API key: the URL is signed and points at storage.googleapis.com, so
    attaching our key would hand it to a third party.
    """
    try:
        resp = httpx.get(url, timeout=300, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise AivdoError(f"could not download the finished ad: {exc}") from exc
    if resp.status_code != 200:
        raise AivdoError(f"downloading the ad returned {resp.status_code}")
    return resp.content
