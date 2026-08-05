import pytest

from app.models import ContentItem
from app.state import InvalidTransition, transition


def make(status: str) -> ContentItem:
    return ContentItem(slug="s", topic="t", status=status)


@pytest.mark.parametrize(
    "src,dst",
    [
        ("idea", "in_review"),
        ("in_review", "approved"),
        ("in_review", "rejected"),
        ("approved", "scheduled"),
        ("scheduled", "posted"),
        ("scheduled", "failed"),
        ("failed", "scheduled"),
        ("rejected", "in_review"),
    ],
)
def test_valid_transitions(src, dst):
    item = make(src)
    transition(item, dst)
    assert item.status == dst


@pytest.mark.parametrize("src,dst", [("idea", "posted"), ("posted", "idea"), ("rejected", "approved")])
def test_invalid_transitions_raise(src, dst):
    with pytest.raises(InvalidTransition):
        transition(make(src), dst)


@pytest.mark.parametrize("src,dst", [("idea", "rendering"), ("failed", "rendering")])
def test_render_transitions_allowed(src, dst):
    item = make(src)
    transition(item, dst)
    assert item.status == dst
