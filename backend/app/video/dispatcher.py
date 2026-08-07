from typing import Protocol

from app.config import Settings


class RenderDispatcher(Protocol):
    def dispatch(self, item_id: str) -> None: ...


class CloudRunDispatcher:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        from google.cloud import run_v2

        return run_v2.JobsClient()

    def dispatch(self, item_id: str) -> None:
        s = self.settings
        name = f"projects/{s.gcp_project}/locations/{s.render_job_region}/jobs/{s.render_job_name}"
        self._client().run_job(
            request={
                "name": name,
                "overrides": {
                    "container_overrides": [
                        {"env": [{"name": "ITEM_ID", "value": item_id}]}
                    ]
                },
            }
        )


class LocalDispatcher:
    """Runs the worker in a subprocess — used in dev and tests."""

    def dispatch(self, item_id: str) -> None:
        import subprocess
        import sys

        subprocess.Popen(
            [sys.executable, "-m", "app.video.worker"],
            env={**__import__("os").environ, "ITEM_ID": item_id},
        )


def get_dispatcher(settings: Settings) -> RenderDispatcher:
    if settings.render_dispatcher == "local":
        return LocalDispatcher()
    if settings.render_dispatcher == "cloudrun":
        return CloudRunDispatcher(settings)
    raise ValueError(f"unknown render_dispatcher: {settings.render_dispatcher!r}")
