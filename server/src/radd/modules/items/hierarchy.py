"""The kind ladder as SQL: ONE definition of "the epic an item belongs to".

Epic <- issue <- subtask (max depth 3, an epic has no parent), so the walk is at
most two hops. An epic is its own epic: time logged on it rolls up under it, and
`epic.state != Done` returns the epic alongside its work. `service/queries.py`
binds the three aliases once per batch, `slq/ancestors.py` per outer row;
sharing the CASE here keeps them from drifting.
"""

from typing import Any

from sqlalchemy import ColumnElement, case

from .enums import ItemKind


def nearest_epic_case(item: Any, parent: Any, grandparent: Any) -> ColumnElement:
    """The id of the epic `item` belongs to: ITSELF, else its parent, else its
    grandparent — NULL when none of the three is an epic (an issue outside any
    epic, and that issue's subtasks).

    `item`/`parent`/`grandparent` are `aliased(WorkItem)` handles (or the
    mapped class itself for the outer row). The two upward hops must be
    OUTER-joined so a parentless epic still produces its self arm.
    """
    return case(
        (item.kind == ItemKind.EPIC.value, item.id),
        (parent.kind == ItemKind.EPIC.value, parent.id),
        (grandparent.kind == ItemKind.EPIC.value, grandparent.id),
    )
