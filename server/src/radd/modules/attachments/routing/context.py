"""What a routing rule may look at when deciding where an upload lives."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingContext:
    actor_id: uuid.UUID
    source_ip: str | None  # resolved by ClientIpMiddleware (trusted-proxy walk)
    chosen_host_id: uuid.UUID | None  # the user's explicit pick, if any
    filename: str
    content_type: str
    size_bytes: int
    entity_type: str
    entity_id: uuid.UUID
    project_id: uuid.UUID | None  # None for wiki parents
    # Lazy accessor over the buffered upload — only the LLM rule reads bytes,
    # so the common path never copies them.
    content: Callable[[], bytes] | None = None
