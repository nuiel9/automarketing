import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _kebab(text: str) -> str:
    ascii_only = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return re.sub(r"-+", "-", ascii_only).strip("-").lower()


def campaign_slug(fmt: str, topic: str, on: date) -> str:
    week = on.isocalendar().week
    return f"w{week}-{_kebab(fmt)}-{_kebab(topic)}"


def with_utm(url: str, channel: str, campaign: str) -> str:
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query))
    query.update(
        {"utm_source": channel, "utm_medium": "social", "utm_campaign": campaign}
    )
    return urlunparse(parts._replace(query=urlencode(query)))
