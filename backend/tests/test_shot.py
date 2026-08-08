import base64
import os

import pytest

from app.video.shot import ShotError, capture, to_data_uri

FIXTURE = """<!doctype html><meta charset=utf-8>
<body style="margin:0;background:#FDF8F3;height:3000px">
<h1 style="font-size:64px;padding:40px">Eduverse One</h1>
</body>"""


@pytest.mark.slow
def test_capture_is_square(tmp_path):
    """AIVDO's blueprint template frames the photo in an 840x820 window with
    object-fit: cover, so a 9:16 capture would be centre-cropped to a narrow
    horizontal band of the page. Square is what fits that frame.

    Dimensions are read with ffprobe, which the project already depends on --
    no image library is needed just to measure a PNG.
    """
    import subprocess

    page = tmp_path / "p.html"
    page.write_text(FIXTURE, encoding="utf-8")
    out = capture(f"file://{page}", str(tmp_path / "shot.png"), side=600)

    assert os.path.exists(out)
    dims = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert dims == "600,600", f"expected a square capture, got {dims}"


def test_to_data_uri_is_a_png_data_uri(tmp_path):
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    uri = to_data_uri(str(png))

    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == png.read_bytes()


def test_missing_file_raises_shot_error(tmp_path):
    with pytest.raises(ShotError):
        to_data_uri(str(tmp_path / "nope.png"))
