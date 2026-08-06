"""Template variables for automation action params (spec 58b): `{{token}}`
substitution so universal actions (create item / webhook / chat / notify) can
carry the triggering event's facts into their output.

The catalogue is `TOKENS`, served by GET /automations/catalog so the editor can
SHOW what is supported instead of leaving people to guess. It sits next to
`_resolve` deliberately: a documented token that does not resolve renders as a
literal `{{…}}` in somebody's issue title, and a working token nobody documented
is one nobody finds.

Unknown tokens render as-is — visible in the output, debuggable, never an error.

Pure module — tested in tests/test_automation_conditions.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .conditions import EventFacts, _payload_path

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


@dataclass(frozen=True)
class TokenInfo:
    """One documented token, for the editor's reference panel.

    Served rather than written into the SPA because this list and `_resolve`
    below must not drift: a token documented but unresolved renders as literal
    `{{…}}` in someone's issue title, and an unlisted token that works is one
    nobody finds. They are defined side by side here for exactly that reason.
    """

    token: str
    description: str
    #: Only meaningful when the run has a target item — an itemless event (a
    #: schedule tick, a cycle event) resolves these to nothing, and the panel
    #: says so rather than letting someone build a title around a blank.
    needs_item: bool = False


TOKENS: tuple[TokenInfo, ...] = (
    TokenInfo("{{event_type}}", "The event that fired, e.g. item.updated."),
    TokenInfo("{{actor.name}}", "Who caused the event."),
    TokenInfo("{{actor.email}}", "Their email."),
    TokenInfo("{{actor.id}}", "Their user id."),
    TokenInfo("{{item.key}}", "The target item's key, e.g. TD-42.", needs_item=True),
    TokenInfo("{{item.title}}", "Its title.", needs_item=True),
    TokenInfo("{{item.id}}", "Its id.", needs_item=True),
    # Set-shaped tokens (RADD-918). An action running ONCE over many items could
    # previously learn only how MANY there were: `{{matched_count}}` was the
    # entire vocabulary, so "post the stale issues to Slack" could say "12" and
    # not which twelve. At item arity these describe the one item, so the same
    # template reads correctly in both modes.
    TokenInfo("{{items.count}}", "How many items this action is acting on."),
    TokenInfo("{{items.keys}}", "Their keys, comma-separated — TD-42, TD-43."),
    TokenInfo("{{items.list}}", "One per line: `TD-42 — the title`. For chat and email bodies."),
    TokenInfo(
        "{{matched_count}}",
        "How many items a scheduled run matched. Kept for automations written "
        "before {{items.count}}, which is the same number under any trigger.",
    ),
    TokenInfo(
        "{{payload.<path>}}",
        "Anything from the raw event payload, by dotted path — e.g. "
        "{{payload.changes.field}}. Lists join with commas.",
    ),
)


# Spec 69: scheduled runs surface their match count to universal-action
# templates as a bare top-level token (merged into the facts payload).
MATCHED_COUNT_TOKEN = "matched_count"


def _resolve(
    token: str,
    facts: EventFacts,
    item_ctx: dict[str, Any] | None,
    items: list[dict[str, Any]] | None,
) -> str | None:
    if token == "event_type":
        return facts.event_type
    if token == MATCHED_COUNT_TOKEN:
        # The payload's count when a scheduled run supplied one, else the set
        # this action is acting on — so the token means the same thing under
        # every trigger instead of being blank on all but one.
        values = _payload_path(facts.payload, MATCHED_COUNT_TOKEN)
        if values:
            return str(values[0])
        return str(len(items)) if items is not None else None
    if token.startswith("items."):
        return _resolve_items(token.removeprefix("items."), items)
    if token == "actor.id":
        return facts.actor_id
    if token == "actor.email":
        return facts.actor_email
    if token == "actor.name":
        return facts.actor_name
    if token.startswith("payload."):
        values = _payload_path(facts.payload, token.removeprefix("payload."))
        return ", ".join(str(v) for v in values) if values else None
    if token.startswith("item.") and item_ctx is not None:
        value = item_ctx.get(token.removeprefix("item."))
        return None if value is None else str(value)
    return None


def _resolve_items(field: str, items: list[dict[str, Any]] | None) -> str | None:
    """The set-shaped tokens. An empty set resolves to an empty string rather
    than staying verbatim: "0 items" and a blank list are the honest rendering of
    a run that matched nothing, whereas a literal `{{items.keys}}` in the chat
    message reads as a broken automation."""
    if items is None:
        return None
    if field == "count":
        return str(len(items))
    if field == "keys":
        return ", ".join(str(entry.get("key", "")) for entry in items)
    if field == "list":
        return "\n".join(f"{entry.get('key', '')} — {entry.get('title', '')}" for entry in items)
    return None


def render_template(
    text: str,
    facts: EventFacts,
    item_ctx: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> str:
    """Substitute `{{token}}` occurrences; unresolvable tokens stay verbatim."""

    def replace(match: re.Match[str]) -> str:
        resolved = _resolve(match.group(1), facts, item_ctx, items)
        return match.group(0) if resolved is None else resolved

    return _TOKEN_RE.sub(replace, text)
