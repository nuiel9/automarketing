from app.config import Settings
from app.video.dispatcher import CloudRunDispatcher, LocalDispatcher, get_dispatcher


def test_get_dispatcher_selects_by_setting():
    assert isinstance(get_dispatcher(Settings(render_dispatcher="local")), LocalDispatcher)
    assert isinstance(get_dispatcher(Settings(render_dispatcher="cloudrun")), CloudRunDispatcher)


def test_cloudrun_dispatch_builds_expected_job_path(monkeypatch):
    settings = Settings(render_dispatcher="cloudrun", gcp_project="p",
                        render_job_region="asia-southeast1", render_job_name="automarketing-render")
    captured = {}

    class FakeJobs:
        def run_job(self, request):
            captured["request"] = request

    monkeypatch.setattr(CloudRunDispatcher, "_client", lambda self: FakeJobs())
    CloudRunDispatcher(settings).dispatch("item123")

    req = captured["request"]
    assert req["name"] == "projects/p/locations/asia-southeast1/jobs/automarketing-render"
    override = req["overrides"]["container_overrides"][0]
    assert {"name": "ITEM_ID", "value": "item123"} in override["env"]
