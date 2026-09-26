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

# A read-restricted builtin field (spec 50) -> the attributes it blanks, and to
# what. ONE map for the API read (`visibility._filter_read`) and the webhook
# payload, so both serve the identical degraded form. Only READ_RESTRICTABLE_BUILTINS
# appear (title/state/priority are never restrictable — see fields.types).
BLANK_BUILTIN: dict[str, dict[str, Any]] = {
    "description": {"description": "", "email_signature": None},
    "assignee": {"assignee": None},
    "reporter": {"reporter": None},
    "team": {"team": None},
    "parent": {"parent": None},
    "start_date": {"start_date": None},
    "target_date": {"target_date": None},
    "cycle": {"cycle": None},
    "release": {"release": None},
    "labels": {"labels": []},
    "flagged": {"flagged": False},
    "estimate_points": {"estimate_points": None},
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
            for key, blank in BLANK_BUILTIN.get(name, {}).items():
                if key in item:
                    item[key] = blank
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
