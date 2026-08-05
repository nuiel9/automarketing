from app.models import ContentItem

ITEM_TRANSITIONS: dict[str, set[str]] = {
    "idea": {"in_review"},
    "planned": {"rendering", "rejected"},      # Phase 2+
    "rendering": {"in_review", "failed"},      # Phase 2+
    "in_review": {"approved", "rejected"},
    "approved": {"scheduled"},
    "scheduled": {"posted", "failed"},
    "posted": set(),
    "failed": {"scheduled"},
    "rejected": {"in_review"},
}


class InvalidTransition(Exception):
    pass


def transition(item: ContentItem, to: str) -> None:
    allowed = ITEM_TRANSITIONS.get(item.status, set())
    if to not in allowed:
        raise InvalidTransition(f"{item.status} -> {to} not allowed")
    item.status = to
