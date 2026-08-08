import os
import time

from app.video.compose import Segment
from app.video.ffmpeg import run
from app.video.scenario import Scenario, Step
from app.video.tts import synthesize

VIEWPORT = {"width": 540, "height": 960}   # 2x-scaled to 1080x1920 by the composer


class RenderStepError(Exception):
    def __init__(self, message: str, step_index: int, screenshot_path: str):
        super().__init__(message)
        self.step_index = step_index
        self.screenshot_path = screenshot_path


def _do_step(page, step: Step, base_url: str) -> None:
    if step.action == "goto":
        page.goto(step.url or base_url, timeout=step.timeout_ms)
    elif step.action == "type":
        page.fill(step.selector, "", timeout=step.timeout_ms)
        page.type(step.selector, step.text or "", delay=60)
    elif step.action == "click":
        page.click(step.selector, timeout=step.timeout_ms)
    elif step.action == "wait_for":
        page.wait_for_selector(step.selector, timeout=step.timeout_ms)
    elif step.action == "wait_ms":
        page.wait_for_timeout(step.ms or 0)
    elif step.action == "scroll":
        # `.last`, and never a bare locator. Locator is STRICT (unlike the
        # page.click/page.fill calls above, which take the first DOM match),
        # so a selector matching a repeated element raises "strict mode
        # violation" instead of scrolling -- and a repeated element is the
        # normal case for a scroll step: you scroll to reveal a LIST. A real
        # render died here on a 4-item plan whose cards all carried the same
        # button label.
        # `.last` over `.first` because scrolling to the end of the list is
        # what reveals it; the first match is usually already on screen, so
        # the step would be a no-op and the shot would never move. With a
        # single match the two are identical.
        page.locator(step.selector).last.scroll_into_view_if_needed(timeout=step.timeout_ms)


def render_demo(
    scenario: Scenario, work_dir: str, base_url: str, login: tuple[str, str] | None
) -> list[Segment]:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    os.makedirs(work_dir, exist_ok=True)
    audio_dir = os.path.join(work_dir, "audio")
    narrations = [synthesize(s.narration, audio_dir) for s in scenario.steps]

    video_dir = os.path.join(work_dir, "session")
    marks: list[tuple[float, float]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(
            viewport=VIEWPORT, device_scale_factor=2,
            record_video_dir=video_dir, record_video_size=VIEWPORT,
            locale="th-TH",
        )
        page = context.new_page()
        # t0 must be captured here, immediately after the page (and thus the
        # video recording) is created -- not after goto/login below -- so the
        # mark timeline shares its origin with the recording. Marks captured
        # after goto/login would be offset from the video's real t=0 by
        # however long navigation/login took, causing every cut clip to
        # start too early and show the wrong footage (see task-6 fix report).
        t0 = time.monotonic()
        page.goto(base_url, timeout=60_000)

        if scenario.login and login:
            # Selectors verified against the live eduverse.one/th/login page on
            # 2026-08-08. The app has no data-testid attributes, so these are
            # the real element ids. The submit button MUST be scoped to the
            # form: the page header also carries a type=submit button (the
            # EN/TH language switcher), and an unscoped selector picks that one
            # and silently never logs in.
            email, password = login
            # base_url already carries the locale (…/th), so append only
            # "/login" — appending "/th/login" yields /th/th/login and 404s.
            page.goto(f"{base_url.rstrip('/')}/login", timeout=60_000)
            page.fill("#email", email, timeout=30_000)
            page.fill("#password", password)
            page.click("form button[type=submit]")
            page.wait_for_load_state("networkidle", timeout=60_000)

        for index, step in enumerate(scenario.steps):
            start = time.monotonic() - t0
            try:
                _do_step(page, step, base_url)
            except PlaywrightError as exc:
                shot = os.path.join(work_dir, f"fail_step_{index}.png")
                page.screenshot(path=shot)
                context.close(); browser.close()
                raise RenderStepError(
                    f"step {index} ({step.action} {step.selector or step.url}): {exc}",
                    index, shot,
                ) from exc
            marks.append((start, time.monotonic() - t0))

        session_video = page.video.path()
        context.close()
        browser.close()

    segments = []
    for index, (step, narration) in enumerate(zip(scenario.steps, narrations)):
        start, end = marks[index]
        clip = os.path.join(work_dir, f"step_{index}.mp4")
        run(["ffmpeg", "-y", "-i", session_video, "-ss", f"{start:.3f}",
             "-to", f"{max(end, start + 0.4):.3f}", "-an", "-pix_fmt", "yuv420p", clip])
        segments.append(Segment(clip, narration, fit=step.fit, sound=step.sound))
    return segments
