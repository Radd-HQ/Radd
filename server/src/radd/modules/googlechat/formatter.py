"""Pure event → Google Chat message formatting (spec 47) — tested in
tests/test_connectors.py. Returns None for events the notifier does not post."""

from typing import Any, Protocol

from .types import DOC_PAGE_CREATED_EVENT, ITEM_CREATED_EVENT, SLA_BREACHED_EVENT


class EventLike(Protocol):
    """The two fields the formatter reads off an outbox event row."""

    event_type: str
    payload: dict[str, Any]


def _issue_url(base_url: str, key: str) -> str:
    return f"{base_url}/issues/{key}"


def format_message(event: EventLike, *, selected: frozenset[str], base_url: str) -> str | None:
    """Compact text message for the selected event types; None = do not post
    (unselected type, or a selected type with no formatter/no usable payload)."""
    if event.event_type not in selected:
        return None
    payload = event.payload or {}
    if event.event_type == ITEM_CREATED_EVENT:
        key = payload.get("key", "")
        if not key:
            return None
        title = payload.get("title", "")
        return f"New item {key}: {title}\n{_issue_url(base_url, key)}"
    if event.event_type == SLA_BREACHED_EVENT:
        key = payload.get("item_key", "")
        if not key:
            return None
        policy = payload.get("policy_name", "")
        kind = payload.get("kind", "")
        return f"SLA breached ({kind}) on {key} — policy {policy}\n{_issue_url(base_url, key)}"
    if event.event_type == DOC_PAGE_CREATED_EVENT:
        title = payload.get("title", "")
        if not title:
            return None
        return f"New doc page: {title}\n{base_url}"
    return None
