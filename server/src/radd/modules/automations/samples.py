"""What an event actually carries (RADD-921): payload paths sampled from REAL
outbox events, never synthesized — a hand-written example per type would drift
from twenty modules' `emit` calls. A type that never fired has no sample.
Pure apart from the query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Depth limit. Payloads are shallow by convention, and a runaway nesting would
#: produce a path list nobody can read.
MAX_DEPTH = 4
#: Per-path example values kept. Several because the useful thing about
#: `changes.field` is the RANGE of values it takes, not one of them.
MAX_EXAMPLES = 5


@dataclass
class PayloadPath:
    """One dotted path into a payload, with what has been seen at it — the string
    `{{payload.<path>}}` and the "Event value is" gate take verbatim."""

    path: str
    examples: list[str] = field(default_factory=list)
    #: True when the path is inside a LIST — `changes.field` addresses every
    #: entry's `field`, and `_payload_path` joins them with commas. Worth saying
    #: out loud: a template that reads it can render more than one value.
    repeated: bool = False

    def observe(self, value: Any) -> None:
        text = _render(value)
        if text and text not in self.examples and len(self.examples) < MAX_EXAMPLES:
            self.examples.append(text)


def _render(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return text if len(text) <= 80 else text[:79] + "…"


def payload_paths(payloads: list[dict[str, Any]]) -> list[PayloadPath]:
    """Every addressable path across a set of payloads, with example values.

    Several payloads rather than one because a single event under-describes the
    shape: an `item.updated` that changed the state and one that changed the
    assignee produce different `changes` entries, and someone writing a condition
    needs the union, not whichever happened most recently.
    """
    found: dict[str, PayloadPath] = {}

    def walk(value: Any, prefix: str, depth: int, repeated: bool) -> None:
        if depth > MAX_DEPTH:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{prefix}.{key}" if prefix else str(key), depth + 1, repeated)
            return
        if isinstance(value, list):
            # The path addresses the ELEMENTS, not the list — `_payload_path`
            # descends into every entry and joins, so `changes.field` is a real
            # path and `changes` alone is not a useful one.
            for child in value:
                walk(child, prefix, depth + 1, True)
            return
        if not prefix:
            return
        entry = found.setdefault(prefix, PayloadPath(path=prefix, repeated=repeated))
        entry.repeated = entry.repeated or repeated
        entry.observe(value)

    for payload in payloads:
        walk(payload, "", 0, False)
    return sorted(found.values(), key=lambda entry: entry.path)


def changed_fields(payloads: list[dict[str, Any]]) -> list[str]:
    """Field names seen in the `changes` diffs — what "field changed" can test.

    The gate's field picker otherwise offers a hand-written list of builtins plus
    every custom-field key, which includes fields the event diff never names: a
    condition that can only ever be false, indistinguishable from one that simply
    has not matched yet.
    """
    names: list[str] = []
    for payload in payloads:
        for change in payload.get("changes") or []:
            if isinstance(change, dict) and (name := change.get("field")):
                if str(name) not in names:
                    names.append(str(name))
    return sorted(names)


def schema_paths(schema: dict[str, Any], prefix: str = "", depth: int = 0) -> list[PayloadPath]:
    """The paths a DECLARED payload schema promises (RADD-1331) — `properties`
    walked like a payload, arrays addressing their items. No examples: a
    declared path has no seen value, and inventing one is what RADD-921 refused."""
    if depth > MAX_DEPTH or not isinstance(schema, dict):
        return []
    found: list[PayloadPath] = []
    for key, child in (schema.get("properties") or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if not isinstance(child, dict):
            found.append(PayloadPath(path=path))
            continue
        target, repeated = (child.get("items") or {}, True) if child.get("type") == "array" else (child, False)
        nested = schema_paths(target, path, depth + 1) if isinstance(target, dict) else []
        if nested:
            for entry in nested:
                entry.repeated = entry.repeated or repeated
            found.extend(nested)
        else:
            found.append(PayloadPath(path=path, repeated=repeated))
    return found

