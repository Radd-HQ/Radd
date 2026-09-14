"""The ledger columns (spec 123): what `emit` derives from a payload so that
the audit log can be FILTERED and SEARCHED without reading every row.

Three pure functions, no I/O, each answering one question an auditor asks:

- `project_of`: which project did this happen in? Read from the subject refs
  the kernel already writes (`payload.project`, `payload.item.project`) or a
  bare `project_id` an emitter put there — never resolved here, so the events
  module keeps depending on no plugin.
- `entity_label`: what is this thing called? `RADD-123 Board scroll`, `Role:
  Contributor`, `alice@example.com`. Taken from the entity's own ref when the
  payload carries one, else from the payload's `name`/`title`/`key`/`email`…
  at WRITE time, so the record survives the row's deletion or rename.
- `search_text`: what should free text match? The event's words, the label,
  the changed fields and their old/new values — a trigram index over ONE
  column instead of an ILIKE over the whole JSONB.

Bounded on purpose: a label is 300 characters, the search text 4000. A mail
payload of a megabyte contributes its subject line, not its body.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from radd.kernel import changes as kchanges

LABEL_MAX = 300
SEARCH_MAX = 4000
#: Payload keys that name an entity, in the order an auditor would prefer.
_LABEL_KEYS: tuple[str, ...] = ("name", "title", "email", "version", "label", "full_name", "url")
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str) and _UUID.match(value):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


def _ref_project(ref: Any) -> uuid.UUID | None:
    if not isinstance(ref, dict):
        return None
    project = ref.get("project")
    if isinstance(project, dict):
        return _uuid(project.get("id"))
    return _uuid(ref.get("project_id"))


def project_of(payload: dict[str, Any]) -> uuid.UUID | None:
    """The project an event happened in, from the refs the payload carries."""
    project = payload.get("project")
    if isinstance(project, dict):
        found = _uuid(project.get("id"))
        if found is not None:
            return found
    for key, value in payload.items():
        if key == "changes":
            continue
        found = _ref_project(value)
        if found is not None:
            return found
    return _uuid(payload.get("project_id"))


def entity_label(entity_type: str, payload: dict[str, Any]) -> str | None:
    """The entity's display label at write time, or None when nothing names it."""
    ref = payload.get(entity_type)
    source = ref if isinstance(ref, dict) else payload
    key = source.get("key")
    # An item is `KEY title`, a project `KEY name` — the key alone is a code.
    title = source.get("title") or source.get("name")
    if isinstance(key, str) and isinstance(title, str) and title:
        return f"{key} {title}"[:LABEL_MAX]
    for candidate in (*_LABEL_KEYS, "key"):
        value = source.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()[:LABEL_MAX]
    return None


def _words(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    if isinstance(value, dict):
        out: list[str] = []
        for candidate in ("subject", "name", "key", "title", "field", "placement", "role"):
            out.extend(_words(value.get(candidate)))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_words(item))
        return out
    return []


def search_text(event_type: str, label: str | None, payload: dict[str, Any]) -> str:
    """What free-text search matches for this event."""
    parts: list[str] = [event_type.replace(".", " ").replace("_", " ")]
    if label:
        parts.append(label)
    change_list = payload.get(kchanges.CHANGES_KEY)
    if isinstance(change_list, list):
        for entry in change_list:
            if not isinstance(entry, dict):
                continue
            parts.extend(_words(entry.get("field")))
            parts.extend(_words(entry.get("name")))
            for side in ("from", "to", "added", "removed"):
                parts.extend(_words(entry.get(side)))
    text = " ".join(part for part in parts if part)
    return text[:SEARCH_MAX]
