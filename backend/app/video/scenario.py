import os
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError, model_validator


class ScenarioError(Exception):
    pass


class Step(BaseModel):
    narration: str
    action: Literal["goto", "type", "click", "wait_for", "wait_ms", "scroll"]
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    ms: int | None = None
    sound: Literal["keystroke", "click"] | None = None
    fit: Literal["speedup", "tail", "hold"] = "speedup"
    timeout_ms: int = 30_000

    @model_validator(mode="after")
    def _check_required_fields(self) -> "Step":
        if not self.narration.strip():
            raise ValueError("narration must not be empty")
        needs_selector = {"type", "click", "wait_for", "scroll"}
        if self.action in needs_selector and not self.selector:
            raise ValueError(f"action {self.action} requires a selector")
        if self.action == "goto" and not self.url:
            raise ValueError("action goto requires a url")
        if self.action == "type" and self.text is None:
            raise ValueError("action type requires text")
        if self.action == "wait_ms" and self.ms is None:
            raise ValueError("action wait_ms requires ms")
        return self


class Scenario(BaseModel):
    name: str
    login: bool = True
    steps: list[Step]

    @model_validator(mode="after")
    def _check_steps(self) -> "Scenario":
        if not self.steps:
            raise ValueError("scenario needs at least one step")
        return self


def load_scenario(name: str, root: str) -> Scenario:
    path = os.path.join(root, f"{os.path.basename(name)}.yaml")
    if not os.path.exists(path):
        raise ScenarioError(f"scenario not found: {name}")
    try:
        with open(path, encoding="utf-8") as f:
            return Scenario.model_validate(yaml.safe_load(f))
    except (ValidationError, yaml.YAMLError) as exc:
        raise ScenarioError(f"invalid scenario {name}: {exc}") from exc
