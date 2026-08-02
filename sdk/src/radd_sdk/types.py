# Copyright 2026 the Radd authors
# SPDX-License-Identifier: Apache-2.0
"""Shared SDK types: the event record, checkpoint keys, CLI env vars, tunables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class StateKey(StrEnum):
    """Keys of the runner's JSON checkpoint file."""

    OFFSET = "offset"


class EnvVar(StrEnum):
    """Environment variables the CLI reads when flags are omitted."""

    URL = "RADD_URL"
    TOKEN = "RADD_TOKEN"
    PLUGINS = "RADD_PLUGINS"
    STATE = "RADD_STATE"
    POLL = "RADD_POLL"


#: Name of the function every plugin module must define: ``register(reg)``.
PLUGIN_ENTRYPOINT = "register"
#: Seconds to sleep between polls that returned no events.
DEFAULT_POLL_INTERVAL = 2.0
#: Default page size for ``RaddClient.events``.
DEFAULT_EVENTS_LIMIT = 100
#: The server's hard cap on ``GET /events?limit=`` (used for runner batches).
MAX_EVENTS_LIMIT = 500


@dataclass(frozen=True, slots=True)
class Event:
    """One row of the tracker's durable event outbox (``GET /api/v1/events``)."""

    id: int
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: datetime
    actor_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            id=data["id"],
            event_type=data["event_type"],
            entity_type=data["entity_type"],
            entity_id=data["entity_id"],
            payload=data.get("payload") or {},
            created_at=datetime.fromisoformat(data["created_at"]),
            actor_id=data.get("actor_id"),
        )
