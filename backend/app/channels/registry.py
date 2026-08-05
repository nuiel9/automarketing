import os

from app.channels.base import ChannelAdapter
from app.channels.dryrun import DryRunAdapter
from app.config import Settings


def build_adapters(settings: Settings) -> dict[str, ChannelAdapter]:
    adapters: dict[str, ChannelAdapter] = {}
    for channel in settings.channels():
        if channel == "dryrun":
            adapters["dryrun"] = DryRunAdapter(
                os.path.join(settings.media_root, "dryrun_feed.jsonl")
            )
        elif channel in ("facebook", "instagram"):
            from app.channels.meta import MetaAdapter  # Task 10
            adapters[channel] = MetaAdapter(settings)
        elif channel == "x":
            from app.channels.x import XAdapter  # Task 11
            adapters["x"] = XAdapter(settings)
        elif channel == "line":
            from app.channels.line import LineAdapter  # Task 12
            adapters["line"] = LineAdapter(settings)
    return adapters
