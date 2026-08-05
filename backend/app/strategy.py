import yaml
from pydantic import BaseModel


class Strategy(BaseModel):
    voice: str
    audiences: list[str]
    banned_words: list[str]
    platform_notes: dict[str, str]


def load_strategy(path: str) -> Strategy:
    with open(path, encoding="utf-8") as f:
        return Strategy.model_validate(yaml.safe_load(f))


def banned_violations(strategy: Strategy, texts: list[str]) -> list[str]:
    joined = "\n".join(t for t in texts if t)
    return [w for w in strategy.banned_words if w in joined]
