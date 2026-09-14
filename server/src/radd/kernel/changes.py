"""Field-level change records — the ONE shape every event's diff takes (spec 123).

An `*.updated` event says *what* changed as a list of change entries, at the
payload's top level under `changes` (it describes the event, not the entity):

    {"field": "name", "from": "Old", "to": "New"}            a scalar
    {"field": "permissions", "added": [...], "removed": [...]} a collection
    {"field": "client_secret"}                                 a hidden value —
                                                               it changed; the
                                                               value is never
                                                               recorded
    {"field": "custom_field", "key": "team_size", "name": "Team size", …}

`items/changes.py` produced this shape first (spec 23) and resolved display
names at write time so a record stays true after the state or person it names
is renamed or deleted. This module is the generic half: a JSON-safe snapshot of
an object's fields and a diff over two snapshots, for the forty-odd emitters
that are not items. Values are whatever the emitter put in the snapshot — pass
names, not ids, where a name is what an auditor will read.

`events.emit(changes=…)` writes the list; an event whose `EventTypeSpec` says
`has_changes` and carries none is refused, the RADD-923 pattern (a promise the
emitter cannot forget to keep). `[]` is the explicit "nothing visible changed".

Pure — no I/O, no ORM import — so it is trivially testable and usable from any
plugin through `radd.sdk`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

#: The payload key a diff lives under. Consumers (history, notify, automations,
#: webhooks, audit) all read this one name.
CHANGES_KEY = "changes"


def json_safe(value: Any) -> Any:
    """A value as it will come back out of JSONB: uuids and dates as strings,
    enums as their values, sets as sorted lists, nested containers recursively."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((json_safe(v) for v in value), key=_sort_key)
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return str(value)


def _sort_key(value: Any) -> tuple[int, str]:
    return (0 if value is None else 1, str(value))


def snapshot(obj: Any, fields: Iterable[str]) -> dict[str, Any]:
    """`{field: json_safe(getattr(obj, field))}` — take one BEFORE mutating and
    one after; `diff` the two. A missing attribute reads as None so a snapshot
    of a Pydantic model and of an ORM row compare on equal terms."""
    return {field: json_safe(getattr(obj, field, None)) for field in fields}


def change(field: str, old: Any, new: Any, *, name: str | None = None) -> dict[str, Any] | None:
    """One scalar entry, or None when nothing changed."""
    old, new = json_safe(old), json_safe(new)
    if old == new:
        return None
    entry: dict[str, Any] = {"field": field, "from": old, "to": new}
    if name is not None:
        entry["name"] = name
    return entry


def hidden_change(field: str, *, name: str | None = None) -> dict[str, Any]:
    """"It changed" with no value — secrets, and bodies too large to be worth a
    copy in every event (a description, a page body, a rule definition)."""
    entry: dict[str, Any] = {"field": field}
    if name is not None:
        entry["name"] = name
    return entry


def collection_change(
    field: str, old: Iterable[Any] | None, new: Iterable[Any] | None, *, name: str | None = None
) -> dict[str, Any] | None:
    """An `added`/`removed` entry for a set-like value, or None when equal.
    Order-insensitive; elements are compared by their JSON form."""
    before = _keyed(old)
    after = _keyed(new)
    added = [after[k] for k in after if k not in before]
    removed = [before[k] for k in before if k not in after]
    if not added and not removed:
        return None
    entry: dict[str, Any] = {"field": field, "added": added, "removed": removed}
    if name is not None:
        entry["name"] = name
    return entry


def _keyed(values: Iterable[Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for value in values or ():
        safe = json_safe(value)
        out[_identity(safe)] = safe
    return out


def _identity(safe: Any) -> str:
    if isinstance(safe, (dict, list)):
        return json.dumps(safe, sort_keys=True, default=str)
    return f"{type(safe).__name__}:{safe}"


def diff(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    labels: Mapping[str, str] | None = None,
    hidden: Collection[str] = (),
    collections: Collection[str] = (),
) -> list[dict[str, Any]]:
    """Ordered change entries between two snapshots.

    - `hidden` fields record only that they changed.
    - `collections` fields (and any field whose both sides are lists) record
      `added`/`removed` instead of `from`/`to`.
    - `labels` adds a display `name` to an entry (the way `custom_field`
      entries carry the field's name) — for keys a reader would not recognise.

    Fields keep `before`'s order, then any that only `after` knows.
    """
    changes: list[dict[str, Any]] = []
    keys = list(before) + [k for k in after if k not in before]
    for key in keys:
        old, new = json_safe(before.get(key)), json_safe(after.get(key))
        if old == new:
            continue
        name = labels.get(key) if labels else None
        if key in hidden:
            entry: dict[str, Any] | None = hidden_change(key, name=name)
        elif key in collections or (isinstance(old, list) and isinstance(new, list)):
            entry = collection_change(key, old, new, name=name)
        else:
            entry = change(key, old, new, name=name)
        if entry is not None:
            changes.append(entry)
    return changes


def diff_object(
    obj: Any,
    before: Mapping[str, Any],
    *,
    labels: Mapping[str, str] | None = None,
    hidden: Collection[str] = (),
    collections: Collection[str] = (),
) -> list[dict[str, Any]]:
    """`diff(before, snapshot(obj, before.keys()))` — the common call: snapshot
    the fields you are about to touch, mutate, then diff against the row."""
    return diff(
        before, snapshot(obj, before.keys()), labels=labels, hidden=hidden, collections=collections
    )


def changed_fields(changes: Iterable[Mapping[str, Any]] | None) -> list[str]:
    """The field names a change list touches, in order, deduplicated — what a
    "changed field" filter matches and the search text carries."""
    seen: list[str] = []
    for entry in changes or ():
        field = entry.get("field")
        if isinstance(field, str) and field not in seen:
            seen.append(field)
    return seen
