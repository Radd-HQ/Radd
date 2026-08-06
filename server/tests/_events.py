"""Building event payloads in tests, in the one shape the engine emits (RADD-922).

Seventeen tests hand-rolled their own payload dicts, each a snapshot of whatever
the emitter happened to write the day it was written — which is exactly how the
product ended up with `key`, `item_key`, and nine events carrying neither. A test
that invents its own shape cannot notice when the real one moves.

So: one builder, mirroring `items.service.refs.ref_from`. If the canonical shape
changes again, this file changes and the tests follow.
"""

from __future__ import annotations

import uuid
from typing import Any


def item_ref(
    item_id: uuid.UUID | str | None = None,
    *,
    key: str = "TD-1",
    title: str = "a title",
    state: dict[str, Any] | None = None,
    state_category: str = "todo",
    project_id: uuid.UUID | str | None = None,
    project_key: str = "TD",
    **extra: Any,
) -> dict[str, Any]:
    """The canonical `payload["item"]`."""
    ref: dict[str, Any] = {
        "id": str(item_id or uuid.uuid4()),
        "key": key,
        "title": title,
        "kind": "issue",
        "priority": "normal",
        "state": state
        if state is not None
        else {"id": str(uuid.uuid4()), "name": "Todo", "category": state_category},
        "project": {
            "id": str(project_id or uuid.uuid4()),
            "key": project_key,
            "name": project_key,
        },
        "team": None,
        "assignee": None,
        "reporter": None,
    }
    ref.update(extra)
    return ref


def item_payload(**kwargs: Any) -> dict[str, Any]:
    """A whole item-scoped payload: the ref under `item`, plus event fields.

    `changes` stays TOP-LEVEL — it describes the event, not the item.
    """
    changes = kwargs.pop("changes", None)
    top = {k: kwargs.pop(k) for k in list(kwargs) if k in _TOP_LEVEL}
    payload: dict[str, Any] = {"item": item_ref(**kwargs)}
    if changes is not None:
        payload["changes"] = changes
    payload.update(top)
    return payload


#: Keys that belong to the EVENT rather than the item, so `item_payload` leaves
#: them at the root instead of folding them into the ref.
_TOP_LEVEL = frozenset(
    {
        "excerpt",
        "visibility",
        "author",
        "entity_type",
        "entity_id",
        "policy_id",
        "policy_name",
        "kind_",
        "due_at",
        "rating",
        "comment",
        "to_state",
        "requester",
        "voter",
        "verdict",
    }
)
