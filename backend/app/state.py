from app.models import ContentItem

ITEM_TRANSITIONS: dict[str, set[str]] = {
    "idea": {"in_review", "rendering"},
    "planned": {"rendering", "rejected"},      # Phase 2+
    "rendering": {"in_review", "failed"},      # Phase 2+
    # in_review -> rendering: an item without a video (created but not yet
    # rendered, or already reviewed with captions) can still have one
    # generated -- rendering isn't gated on review status, only on whether
    # media exists (the frontend's render control instead gates on
    # !media_url; see Task 10).
    "in_review": {"approved", "rejected", "rendering"},
    "approved": {"scheduled"},
    "scheduled": {"posted", "failed"},
    "posted": set(),
    "failed": {"scheduled", "rendering"},
    "rejected": {"in_review"},
}


class InvalidTransition(Exception):
    pass


def transition(item: ContentItem, to: str) -> None:
    allowed = ITEM_TRANSITIONS.get(item.status, set())
    if to not in allowed:
        raise InvalidTransition(f"{item.status} -> {to} not allowed")
    item.status = to
