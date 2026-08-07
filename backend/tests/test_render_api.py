from pathlib import Path

import pytest

import app.api.items as items_api
from tests.test_items_api import AUTH, _create, patch_deps  # noqa: F401 -- reuse Phase 1 helpers
# patch_deps is autouse in test_items_api.py, but pytest only auto-applies an
# autouse fixture to tests in modules where it's a bound name -- importing it
# here (rather than just AUTH/_create) is what makes it run for this module's
# tests too, mocking write_captions/load_strategy so _create() below doesn't
# hit the real filesystem/Gemini API.


@pytest.fixture(autouse=True)
def fake_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(items_api, "get_dispatcher",
                        lambda s: type("D", (), {"dispatch": lambda self, i: calls.append(i)})())
    return calls


@pytest.fixture(autouse=True)
def scenario_root(monkeypatch):
    # items_api.SCENARIO_ROOT is `os.environ.get("SCENARIO_ROOT", "./scenarios")`
    # read once at import time, so it's captured relative to whatever cwd the
    # test process started in (backend/, per the run instructions) -- setting
    # an env var here would be too late. Point the module attribute directly
    # at the real tracked fixture (repo root scenarios/fixture-demo.yaml)
    # rather than writing a duplicate YAML into tmp_path, so
    # test_unknown_scenario_is_422 stays meaningful: the root exists, the
    # requested scenario genuinely doesn't.
    monkeypatch.setattr(
        items_api, "SCENARIO_ROOT", str(Path(__file__).resolve().parents[2] / "scenarios")
    )


def test_render_moves_item_to_rendering_and_dispatches(client_with_db, db, fake_dispatch):
    # Deliberately not _create(): that helper uploads a file and always runs
    # _generate(), which transitions idea -> in_review on caption success --
    # so a _create()d item is never a valid "idea"/no-media render candidate
    # (state.py only allows idea -> rendering and failed -> rendering; see
    # Task 10's own render-button guard: status in (idea, failed) with no
    # media_url). Construct the item directly in "idea", same pattern as
    # test_render_from_posted_item_is_409 below.
    from app.models import ContentItem
    item = ContentItem(slug="w32-video-x", topic="t", status="idea")
    db.add(item); db.commit()
    resp = client_with_db.post(
        f"/api/items/{item.id}/render",
        json={"format": "demo", "scenario": "fixture-demo"}, headers=AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rendering"
    assert body["scenario"] == "fixture-demo"
    assert fake_dispatch == [item.id]


def test_demo_without_scenario_is_422(client_with_db):
    item = _create(client_with_db).json()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/render", json={"format": "demo"}, headers=AUTH
    )
    assert resp.status_code == 422


def test_unknown_scenario_is_422(client_with_db):
    item = _create(client_with_db).json()
    resp = client_with_db.post(
        f"/api/items/{item['id']}/render",
        json={"format": "demo", "scenario": "no-such-scenario"}, headers=AUTH,
    )
    assert resp.status_code == 422


def test_render_from_posted_item_is_409(client_with_db, db):
    from app.models import ContentItem
    item = ContentItem(slug="s", topic="t", status="posted")
    db.add(item); db.commit()
    resp = client_with_db.post(
        f"/api/items/{item.id}/render", json={"format": "tips"}, headers=AUTH
    )
    assert resp.status_code == 409
