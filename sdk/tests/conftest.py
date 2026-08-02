"""Shared fixtures: a stub event source and an Event factory (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radd_sdk.types import Event


def make_event(event_id: int, event_type: str = "item.created") -> Event:
    return Event(
        id=event_id,
        event_type=event_type,
        entity_type="item",
        entity_id=f"entity-{event_id}",
        payload={"n": event_id},
        created_at=datetime.now(UTC),
    )


class StubClient:
    """EventSource stub: serves canned batches and records every poll's `after`."""

    def __init__(self, batches: list[list[Event]] | None = None) -> None:
        self._batches = list(batches or [])
        self.polled_after: list[int] = []

    def events(self, after: int = 0, limit: int = 500) -> list[Event]:
        self.polled_after.append(after)
        return self._batches.pop(0) if self._batches else []


@pytest.fixture
def stub_client() -> StubClient:
    return StubClient()
