import logging
import os
import tempfile

from app.config import get_settings
from app.db import SessionLocal
from app.media import get_store
from app.models import ContentItem
from app.notify import line_notify
from app.state import transition
from app.strategy import load_strategy
from app.video.compose import compose
from app.video.demo import RenderStepError, render_demo
from app.video.scenario import ScenarioError, load_scenario
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


def render_item(session, item_id: str, notify=line_notify) -> None:
    item = session.get(ContentItem, item_id)
    if item is None:
        return

    with tempfile.TemporaryDirectory(prefix="render-") as work_dir:
        try:
            segments, hook = _render_segments(item, work_dir)
            mp4, poster = compose(segments, hook, work_dir)
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
