from datetime import date
from urllib.parse import parse_qs, urlparse

from app.utm import campaign_slug, with_utm


def test_campaign_slug_ascii_and_week():
    slug = campaign_slug("founder_clip", "TGAT คณิต ep.1", date(2026, 8, 5))
    assert slug == "w32-founder-clip-tgat-ep-1"  # Thai chars dropped, ascii kebab


def test_with_utm_adds_params_and_keeps_existing():
    url = with_utm("https://eduverse.one/signup?ref=a", "tiktok", "w32-demo-tgat")
    q = parse_qs(urlparse(url).query)
    assert q["ref"] == ["a"]
    assert q["utm_source"] == ["tiktok"]
    assert q["utm_medium"] == ["social"]
    assert q["utm_campaign"] == ["w32-demo-tgat"]
