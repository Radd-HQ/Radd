"""Connection interests and payload-free invalidation routing.

Project interests are validated against the session's readable projects.
Unscoped/legacy queries retain coarse entity pings; notification pings remain
private to their recipient. Record reads always enforce their own permissions.
"""

import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from radd.modules.events.service import Event

from .types import NOTIFICATION_ENTITY


@dataclass
class ClientInfo:
    user_id: uuid.UUID
    subscriptions: list[dict] | None = None


@dataclass
class InvalidationEvent:
    """One coalesced signal; scope is internal and never sent to clients."""
    entity_type: str
    event_type: str
    payload: dict
    item_ids: set[str] | None
    silent: bool = False


def event_project_id(event: Event) -> str | None:
    payload = event.payload or {}
    item = payload.get("item")
    item = item if isinstance(item, dict) else {}
    project = item.get("project") or payload.get("project")
    project = project if isinstance(project, dict) else {}
    value = project.get("id") or item.get("project_id") or payload.get("project_id")
    return str(value) if value else None


def query_targets(info: ClientInfo, event: Event) -> list[str] | None:
    """Echo only this client's query identities; never publish project/item IDs."""
    if info.subscriptions is None:
        return None  # compatibility with older clients
    project_id = event_project_id(event)
    item_ids = event_item_ids(event)
    return [
        sub["id"]
        for sub in info.subscriptions
        if event.entity_type in sub["entities"]
        and (not sub.get("project_id") or project_id is None or sub["project_id"] == project_id)
        and (not sub.get("item_ids") or item_ids is None or item_ids.intersection(sub["item_ids"]))
    ]


def event_item_ids(event) -> set[str] | None:
    if isinstance(event, InvalidationEvent):
        return event.item_ids
    item_id = scoped_event_item_id(event)
    return {item_id} if item_id is not None else None


def scoped_event_item_id(event: Event) -> str | None:
    """Only narrow events with proven record-local effects.

    Membership, hierarchy, links and visibility can change representations of
    records that did not previously reference the changed item. Those retain
    broad invalidation, as do legacy/unknown payloads and configuration events.
    """
    payload = event.payload or {}
    if event.entity_type == "item":
        if getattr(event, "event_type", None) != "item.updated":
            return None
        changes = payload.get("changes")
        # Text can add/remove automatic mention backlinks, even when the
        # writer cannot see the target. Retain broad refresh for text edits.
        local_fields = {"priority", "flagged", "estimate_points",
                        "start_date", "target_date", "rank"}
        if not isinstance(changes, list) or any(
            not isinstance(change, dict) or change.get("field") not in local_fields
            for change in changes
        ):
            return None
    elif event.entity_type not in {"comment", "worklog", "item_estimate", "web_link", "vcs_link"}:
        return None
    item = payload.get("item")
    return str(item["id"]) if isinstance(item, dict) and item.get("id") else None


def validate_subscriptions(raw: object, readable: set[str]) -> list[dict] | None:
    if raw is None:
        return None  # explicit compatibility fallback, still payload-free
    if not isinstance(raw, list) or len(raw) > 128:
        raise ValueError("invalid realtime subscriptions")
    result = []
    for sub in raw:
        if not isinstance(sub, dict) or not isinstance(sub.get("id"), str) or len(sub["id"]) > 4096:
            raise ValueError("invalid query identity")
        entities = sub.get("entities")
        if (
            not isinstance(entities, list)
            or len(entities) > 64
            or any(not isinstance(e, str) or len(e) > 64 for e in entities)
        ):
            raise ValueError("invalid entity subscriptions")
        project_id = sub.get("project_id")
        if project_id is not None and (
            not isinstance(project_id, str) or project_id not in readable
        ):
            continue  # permission-scoped interests fail closed
        item_ids = sub.get("item_ids")
        if item_ids is not None:
            if not isinstance(item_ids, list) or len(item_ids) > 128:
                raise ValueError("invalid item subscriptions")
            if any(not isinstance(value, str) for value in item_ids):
                raise ValueError("invalid item subscriptions")
            item_ids = list(dict.fromkeys(str(uuid.UUID(value)) for value in item_ids))
        result.append({"id": sub["id"], "entities": entities, "project_id": project_id,
                       "item_ids": item_ids})
    return result


async def authorize_item_subscriptions(session, actor, subscriptions):
    """Validate all requested record interests in one authorized batch.

    An unavailable record falls back to a coarse ping. This both avoids a
    guessed-ID existence oracle and allows revoked/restored access to refresh.
    """
    if not subscriptions:
        return subscriptions
    from radd.config import settings
    if "radd.modules.items" not in settings.modules:
        for sub in subscriptions:
            sub["item_ids"] = None
        return subscriptions
    from radd.modules.items import service as items

    ids = {uuid.UUID(value) for sub in subscriptions for value in sub.get("item_ids") or ()}
    if not ids:
        return subscriptions
    readable = await items.readable_item_ids(session, actor, ids)
    for sub in subscriptions:
        if any(uuid.UUID(value) not in readable for value in sub.get("item_ids") or ()):
            sub["item_ids"] = None
    return subscriptions


def should_deliver(info: ClientInfo, event: Event) -> bool:
    """Route one outbox event to one connection (pure — tested).

    - notification events are private: only their recipient sees them
    - every other event frame goes to every authenticated connection
    """
    if event.entity_type == NOTIFICATION_ENTITY:
        recipient = (event.payload or {}).get("user_id")
        return recipient == str(info.user_id)
    return True


@dataclass
class Hub:
    connections: dict[WebSocket, ClientInfo] = field(default_factory=dict)

    def register(self, websocket: WebSocket, info: ClientInfo) -> None:
        self.connections[websocket] = info

    def unregister(self, websocket: WebSocket) -> None:
        self.connections.pop(websocket, None)


hub = Hub()
