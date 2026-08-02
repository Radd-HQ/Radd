"""Template variables for automation action params (spec 58b): `{{token}}`
substitution so universal actions (create item / webhook / chat / notify) can
carry the triggering event's facts into their output.

Tokens: `{{event_type}}`, `{{actor.id|email|name}}`, `{{payload.<dotted.path>}}`
(first resolved value; lists join with ", "), and `{{item.key|title|id}}` when
the event resolved a target item. Unknown tokens render as-is — visible in the
output, debuggable, never an error.

Pure module — tested in tests/test_automation_conditions.py.
"""

from __future__ import annotations

import re
from typing import Any

from .conditions import EventFacts, _payload_path

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


# Spec 69: scheduled runs surface their match count to universal-action
# templates as a bare top-level token (merged into the facts payload).
MATCHED_COUNT_TOKEN = "matched_count"


def _resolve(token: str, facts: EventFacts, item_ctx: dict[str, Any] | None) -> str | None:
    if token == "event_type":
        return facts.event_type
    if token == MATCHED_COUNT_TOKEN:
        values = _payload_path(facts.payload, MATCHED_COUNT_TOKEN)
        return str(values[0]) if values else None
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


def render_template(
    text: str, facts: EventFacts, item_ctx: dict[str, Any] | None = None
) -> str:
    """Substitute `{{token}}` occurrences; unresolvable tokens stay verbatim."""

    def replace(match: re.Match[str]) -> str:
        resolved = _resolve(match.group(1), facts, item_ctx)
        return match.group(0) if resolved is None else resolved

    return _TOKEN_RE.sub(replace, text)
