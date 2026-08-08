import yaml
from pydantic import BaseModel


class MusicConfig(BaseModel):
    """Background-music beds, per video format.

    Each format names a list of CC0 track ids; one is chosen per item (see
    app.video.music.pick_track). Listing several is what keeps the feed from
    carrying identical audio on every post. An empty list -- or no `music`
    block at all -- means that format ships without music, which is the
    pre-feature behaviour and must stay a valid configuration.
    """

    tips: list[str] = []
    demo: list[str] = []
    motion_ad: list[str] = []
    # Absolute loudness the bed is normalised to BEFORE it is mixed under the
    # narration. -33 LUFS is AIVDO's Motion Ad value, which is deliberately
    # far below the -24 the final mix is normalised to: the bed is meant to
    # be felt, not heard over a Thai voiceover. Raising this toward -24 will
    # start burying the narration.
    gain_lufs: float = -33.0

    def for_format(self, fmt: str) -> list[str]:
        return {
            "tips": self.tips,
            "demo": self.demo,
            "motion_ad": self.motion_ad,
        }.get(fmt, [])


class Strategy(BaseModel):
    voice: str
    audiences: list[str]
    banned_words: list[str]
    platform_notes: dict[str, str]
    music: MusicConfig = MusicConfig()


def load_strategy(path: str) -> Strategy:
    with open(path, encoding="utf-8") as f:
        return Strategy.model_validate(yaml.safe_load(f))


def banned_violations(strategy: Strategy, texts: list[str]) -> list[str]:
    joined = "\n".join(t for t in texts if t)
    return [w for w in strategy.banned_words if w in joined]
