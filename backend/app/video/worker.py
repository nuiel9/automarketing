import io
import logging
import os
import tempfile

from app.config import get_settings
from app.db import SessionLocal
from app.media import get_store
from app.models import ContentItem
from app.notify import line_notify
from app.state import transition
from app.strategy import MusicConfig, load_strategy
from app.video.ad_copy import write_ad_copy
from app.video.aivdo import download, generate_ad, poll
from app.video.compose import compose
from app.video.demo import RenderStepError, render_demo
from app.video.music import pick_track, pick_track_id
from app.video.scenario import ScenarioError, load_scenario
from app.video.shot import capture, to_data_uri
from app.video.tips import render_tips, write_tips

log = logging.getLogger(__name__)

SCENARIO_ROOT = os.environ.get("SCENARIO_ROOT", "./scenarios")


def _render_segments(item: ContentItem, work_dir: str):
    """Returns (segments, hook_text)."""
    settings = get_settings()
    if item.format == "demo":
        scenario = load_scenario(item.scenario or "", SCENARIO_ROOT)
        login = (
            (settings.demo_email, settings.demo_password)
            if scenario.login and settings.demo_email
            else None
        )
        segments = render_demo(
            scenario, work_dir, base_url="https://eduverse.one/th", login=login
        )
        return segments, item.hook or ""
    if item.format == "tips":
        tips = write_tips(item.topic, load_strategy(settings.strategy_path))
        return render_tips(tips, work_dir), item.hook or tips.hook
    raise ValueError(f"format {item.format} is not renderable")


def _render_motion_ad(session, item: ContentItem, work_dir: str) -> bytes:
    """Produce a finished Motion Ad MP4 via AIVDO.

    Returns the video bytes rather than Segments: this format never touches
    compose(). AIVDO renders the whole 11-second spot, so there are no
    subtitles, no local music bed and no hook overlay on this path.
    """
    settings = get_settings()

    job_id = item.aivdo_job_id
    if not job_id:
        # strategy is only needed on the dispatch path (write_ad_copy,
        # pick_track_id below) -- loaded here, not above, so that resuming a
        # job whose 5 credits are ALREADY spent can never be blocked by a
        # config load it doesn't need.
        strategy = load_strategy(settings.strategy_path)
        # Order matters. The screenshot and the copy are free; generate_ad
        # spends 5 credits. Anything that can fail cheaply fails first --
        # including the banned-words gate inside write_ad_copy.
        png = capture(settings.ad_shot_url, os.path.join(work_dir, "shot.png"))
        copy = write_ad_copy(item.topic, strategy)
        track_id = pick_track_id(strategy.music.for_format("motion_ad"), item.id)
        job_id = generate_ad(
            to_data_uri(png),
            f"Eduverse One: {item.topic}",
            copy.as_payload(),
            track_id,
        )
        # Commit before polling. Those credits are already spent; if this
        # process dies now, the retry must resume THIS job rather than pay
        # for a second one.
        item.aivdo_job_id = job_id
        session.commit()

    return download(poll(job_id, settings.aivdo_poll_timeout))


def _upload_screenshot(path: str | None) -> str | None:
    """Best-effort upload of a RenderStepError's failure screenshot.

    Returns the stored reference, or None if there's nothing to upload or
    the upload itself fails -- a screenshot is a bonus for the founder
    diagnosing the failure, not something that may itself crash the
    exception handler and swallow the original error message/notification.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        store = get_store(get_settings())
        with open(path, "rb") as f:
            return store.save(f, os.path.basename(path))
    except Exception:
        # Distinguish "upload failed" from "no screenshot existed" in the
        # logs -- both currently return None to the caller by design (a
        # broken screenshot upload must not itself crash the exception
        # handler), but a silent failure here is otherwise indistinguishable
        # from a future regression that stops passing a screenshot at all.
        log.warning("failed to upload failure screenshot %s", path, exc_info=True)
        return None


def _music_for(item: ContentItem) -> tuple[str | None, float]:
    """(track path, gain) for this item, or (None, default) if unavailable.

    Every failure here degrades to "this video has no music" instead of
    propagating. Music is a polish layer: a malformed strategy.yaml or a
    track missing from the image must not be able to fail a render that
    would otherwise have produced a perfectly good video -- and note that
    before music existed, a demo render did not read strategy.yaml at all,
    so raising here would newly break renders that used to work.
    """
    default_gain = MusicConfig().gain_lufs
    try:
        strategy = load_strategy(get_settings().strategy_path)
        # Keyed on the item id so a re-render after a fix keeps the same
        # track instead of swapping the soundtrack under a reviewer who
        # already approved how it sounded.
        return pick_track(strategy.music.for_format(item.format), item.id), strategy.music.gain_lufs
    except Exception:
        log.warning("music unavailable for item %s; rendering without a bed",
                    item.id, exc_info=True)
        return None, default_gain


def render_item(session, item_id: str, notify=line_notify) -> None:
    item = session.get(ContentItem, item_id)
    if item is None:
        return

    with tempfile.TemporaryDirectory(prefix="render-") as work_dir:
        try:
            if item.format == "motion_ad":
                video_bytes = _render_motion_ad(session, item, work_dir)
                store = get_store(get_settings())
                # No poster for this format. The other path saves one, but
                # nothing reads it back -- items.py's media_url and the
                # /media/{token} route both key off media_path alone -- and
                # AIVDO returns only the MP4.
                item.media_path = store.save(io.BytesIO(video_bytes), "video.mp4")
                item.render_error = None
                transition(item, "in_review")
            else:
                segments, hook = _render_segments(item, work_dir)
                # Tips cards already display their headline and body as
                # on-screen text, so burning the same narration over them as
                # subtitles is redundant and collides with that text (two
                # layers of Thai fighting each other). A demo screen-recording
                # has no text of its own, so burned subtitles are essential
                # there.
                track, gain = _music_for(item)
                mp4, poster = compose(
                    segments, hook, work_dir, subtitles=item.format == "demo",
                    music_track=track, music_lufs=gain,
                )
                store = get_store(get_settings())
                with open(mp4, "rb") as f:
                    video_ref = store.save(f, "video.mp4")
                with open(poster, "rb") as f:
                    store.save(f, "poster.jpg")
                # Only point the item at the uploaded video once BOTH uploads
                # have succeeded. Assigning item.media_path right after the
                # video upload (before the poster upload could still raise)
                # would let a poster-upload failure land the item in "failed"
                # while media_path still pointed at a real, playable video --
                # both items.py's media_url and the /media/{token} route gate
                # only on media_path being truthy, never on status, so the
                # founder would see a failed item that plays.
                item.media_path = video_ref
                item.render_error = None
                transition(item, "in_review")
        except Exception as exc:
            detail = str(exc)[:2000]
            suffix = ""
            if isinstance(exc, RenderStepError):
                ref = _upload_screenshot(exc.screenshot_path)
                if ref:
                    suffix = f" [screenshot: {ref}]"
            item.render_error = detail + suffix
            if item.status == "rendering":
                transition(item, "failed")
            # suffix appended after truncating detail (not inside the
            # [:300] cut) so the screenshot reference -- the whole point of
            # correction 3 -- survives into the LINE alert even when detail
            # (e.g. a Playwright timeout's multi-line "Call log:" block) is
            # long enough on its own to fill the 300-char budget.
            notify(f"[AutoMarketing] render failed for {item.slug}: {detail[:300]}{suffix}")
        finally:
            try:
                session.commit()
            except Exception:
                # On the failure branch notify() has already fired, so the
                # founder still hears about it even if this commit is lost.
                # On the success branch there is no such backstop -- a
                # commit failure here would otherwise leave the item stuck
                # in "rendering" with nothing logged anywhere. Log either
                # way and re-raise so the caller (e.g. the dispatcher) still
                # sees the failure.
                log.exception("render_item: failed to commit result for item %s", item_id)
                raise


def main() -> None:
    item_id = os.environ["ITEM_ID"]
    with SessionLocal() as session:
        render_item(session, item_id)
        session.commit()


if __name__ == "__main__":
    main()
