"""Redacting item-event payloads for consumers that can hold no grant (RADD-1085).

An item event's payload deliberately carries the FULL read (service/read.py
`_finish`): in-process consumers are trusted and enforce their own authz at
their own edges. A webhook endpoint is neither — it is an anonymous socket
with a signing secret, it can hold no field grant and sit in no team — so
anything read-restricted for ANYBODY is restricted for it. The sets come from
`fields.outbound_restricted_keys` (fail-closed, instance-wide); this module is
PURE so the policy is unit-testable without a database.

Copy-on-write: the input dict is an ORM row's JSONB payload — mutating it in
place would dirty the events row and rewrite history on the next flush.
"""

from typing import Any

# Dict-level mirror of visibility._BLANK_BUILTIN: the same shapes a blanked
# API read serves, so a webhook receiver sees the identical degraded form.
_BLANKED: dict[str, Any] = {
    "description": "",
    "assignee": None,
    "reporter": None,
    "team": None,
    "parent": None,
    "start_date": None,
    "target_date": None,
    "cycle": None,
    "release": None,
    "labels": [],
    "flagged": False,
    "estimate_points": None,
}


def redact_item_payload(
    payload: dict[str, Any] | None,
    custom_keys: frozenset[str],
    builtin_names: frozenset[str],
) -> dict[str, Any]:
    """Strip restricted custom fields and blank restricted builtins from an
    event payload's `item` (and drop their `changes` entries — a diff that
    says `salary: 100k -> 120k` leaks both values)."""
    if payload is None:
        return {}
    if not custom_keys and not builtin_names:
        return payload
    out = dict(payload)
    item = out.get("item")
    if isinstance(item, dict):
        item = dict(item)
        custom_fields = item.get("custom_fields")
        if custom_keys and isinstance(custom_fields, dict):
            item["custom_fields"] = {
                k: v for k, v in custom_fields.items() if k not in custom_keys
            }
        for name in builtin_names:
            if name in _BLANKED and name in item:
                item[name] = _BLANKED[name]
        out["item"] = item
    changes = out.get("changes")
    if isinstance(changes, list):
        kept = [
            entry
            for entry in changes
            if not (
                entry.get("field") in builtin_names
                or (entry.get("field") == "custom_field" and entry.get("key") in custom_keys)
            )
        ]
        if len(kept) != len(changes):
            out["changes"] = kept
    return out
