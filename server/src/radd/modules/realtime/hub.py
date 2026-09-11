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
    return [
        sub["id"]
        for sub in info.subscriptions
        if event.entity_type in sub["entities"]
        and (not sub.get("project_id") or project_id is None or sub["project_id"] == project_id)
    ]


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
        result.append({"id": sub["id"], "entities": entities, "project_id": project_id})
    return result


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
