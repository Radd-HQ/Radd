"""Board bucket expressions and index-friendly single-bucket predicates."""

import uuid
from .slq.catalog import SlqField
from sqlalchemy import String, cast, func, literal
from radd.modules.workflow.models import State
from .models import WorkItem
from .slq.errors import SlqError


#: The epic bucket for work whose nearest epic (or the rung on the way to it) the
#: actor may not read (RADD-1491) — distinct from `__no_epic__`, which is work
#: no epic governs. Both are group keys the SPA labels.
HIDDEN_EPIC_BUCKET = "__hidden_epic__"
NO_EPIC_BUCKET = "__no_epic__"


def axis_expression(axis, project_id, epic):
    values = {
        "state": cast(WorkItem.state_id, String) if project_id else State.name,
        "state_category": State.category_key,
        "priority": WorkItem.priority,
        "kind": WorkItem.kind,
        "assignee": func.coalesce(cast(WorkItem.assignee_id, String), "__unassigned__"),
        "team": func.coalesce(cast(WorkItem.team_id, String), "__no_team__"),
        "cycle": func.coalesce(cast(WorkItem.cycle_id, String), "__backlog__"),
        "epic": func.coalesce(cast(epic, String), NO_EPIC_BUCKET),
        None: literal("__all__"),
    }
    if axis and axis.startswith("cf."):
        return func.coalesce(func.nullif(WorkItem.custom_fields[axis[3:]].astext, ""), "__none__")
    if axis not in values:
        raise SlqError(f"Unsupported grouping axis: {axis}", 0)
    return values[axis]


def bucket_filter(axis, key, expression, project_id):
    # Match UUID columns directly, so per-column reads can use their indexes.
    # Applying coalesce(cast(...)) in WHERE forces scans on large boards.
    columns = {
        "assignee": (WorkItem.assignee_id, "__unassigned__"),
        "team": (WorkItem.team_id, "__no_team__"),
        "cycle": (WorkItem.cycle_id, "__backlog__"),
    }
    if axis == SlqField.STATE and project_id:
        columns["state"] = (WorkItem.state_id, None)
    if axis not in columns:
        return expression == key
    field, unset = columns[axis]
    if key == unset:
        return field.is_(None)
    try:
        return field == uuid.UUID(key)
    except ValueError:
        from sqlalchemy import false

        return false()
