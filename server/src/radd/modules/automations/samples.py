"""What an event actually carries (RADD-921).

Every condition an automation can write against an event names a path into its
payload — `{{payload.changes.field}}` in a template, a dotted path in the
`payload` condition subject, a field name in "field changed". None of that was
discoverable: you wrote the path, saved, waited for the event to fire, and found
out from the absence of an effect that you had guessed wrong. The catalog said
which events EXIST; nothing said what any of them contains.

**Sampled from real events, never synthesized.** A hand-written example per event
type would be a second copy of a shape defined in twenty modules' `emit` calls,
and it would drift silently — the failure mode here is precisely a payload that
looks right and isn't. Reading the outbox is also the only way the answer stays
correct when a plugin adds a field. The cost is honest and stated: an event type
that has never fired has no sample, and the UI says so rather than inventing one.

Pure module apart from the query — the flattening is where the decisions are, and
it is unit-tested without a database.
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
    """One dotted path into a payload, with what has been seen at it.

    `{{payload.<path>}}` and the `payload` condition subject both take exactly
    this string, so the panel that shows them can insert them verbatim.
    """

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
