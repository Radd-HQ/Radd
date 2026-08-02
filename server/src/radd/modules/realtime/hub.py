"""In-memory connection registry + the pure delivery predicate.

Messages carry no payload data (only entity/event_type ids), so delivery is a
coarse filter: the worst a misdelivered message causes is a refetch of
endpoints that are themselves RBAC'd. Spec 86 stage 1: the workspace-membership
check is gone — every AUTHENTICATED connection sees entity frames; only
notification frames stay per-recipient.
"""

import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from radd.modules.events.models import Event

from .types import NOTIFICATION_ENTITY


@dataclass(frozen=True)
class ClientInfo:
    user_id: uuid.UUID


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
