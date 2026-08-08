"""Screenshot a public page for use as the Motion Ad's product photo.

Square, not 9:16. AIVDO's `blueprint` template positions the photo as
`#spec { left:120px; right:120px; top:360px; height:820px }` -- an 840x820
window with the ad copy drawn OUTSIDE it -- and `#photo` uses
`object-fit: cover`. A 1080x1920 capture would be centre-cropped to a narrow
horizontal band of the page.

No login, deliberately. That keeps the demo account's credentials out of this
path entirely and avoids the goal-accumulation side effect the `demo`
scenario has on the production account.
"""

import base64
import os


class ShotError(Exception):
    pass


def capture(url: str, out_path: str, side: int = 1080) -> str:
    """Screenshot `url` into a square PNG of `side`x`side` pixels."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    # device_scale_factor=2 renders at 2x and downsamples, so page text stays
    # legible after AIVDO scales the photo into its frame.
    half = max(1, side // 2)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            context = browser.new_context(
                viewport={"width": half, "height": half},
                device_scale_factor=2, locale="th-TH",
            )
            page = context.new_page()
            page.goto(url, timeout=60_000, wait_until="networkidle")
            # Settle web fonts and any entrance animation before capturing;
            # networkidle fires before those have painted.
            page.wait_for_timeout(1500)
            page.screenshot(path=out_path)
            browser.close()
    except PlaywrightError as exc:
        raise ShotError(f"could not capture {url}: {exc}") from exc
    except OSError as exc:
        raise ShotError(f"could not write screenshot to {out_path}: {exc}") from exc
    return out_path


def to_data_uri(path: str) -> str:
    """Read a PNG into the `data:` URI form AIVDO's API expects."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise ShotError(f"could not read screenshot {path}: {exc}") from exc
    return "data:image/png;base64," + base64.b64encode(raw).decode()
