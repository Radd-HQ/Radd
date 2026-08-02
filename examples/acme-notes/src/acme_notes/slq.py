"""Make issues searchable by their notes in SLQ — `note ~ "text"` (contains) / `note = "text"`.

The plugin declares an `SlqFieldSpec` (see `__init__.py`) whose resolver returns a Select of the
work-item ids whose notes match. The items query engine wraps it as `work_item.id IN (…)` — so the
plugin extends the query language touching only its OWN table (`acme_notes`), reached through the
public SDK's `entities.model_for`.
"""

from typing import Any

from sqlalchemy import select

from radd.kernel import SlqFieldContext
from radd.sdk import entities


def note_item_ids(contains: bool, value: str, ctx: SlqFieldContext) -> Any:
    """(contains, value, ctx) -> Select of work_item ids that have a matching note.

    `ctx` carries the acting user (for fields that honour the `me` literal);
    notes match on body alone, so it goes unused here."""
    Note = entities.model_for("note")
    condition = Note.body.ilike(f"%{value}%") if contains else Note.body == value
    return select(Note.item_id).where(Note.item_id.isnot(None)).where(condition)
