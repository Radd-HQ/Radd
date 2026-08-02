"""The kind ladder as SQL: ONE definition of "the epic an item belongs to".

`REQUIRED_PARENT_KIND` (enums) makes the hierarchy epic <- issue <- subtask,
max depth 3, and forbids an epic a parent at all — so every item has AT MOST
ONE epic in scope and the walk is at most two hops.

**An item that IS an epic is its own epic.** That is not a special case bolted
on: `epic` names the epic an item belongs to, and an epic belongs to itself.
Time logged straight onto an epic rolls up under it rather than under "no
epic", and `epic.state != Done` returns the unfinished epic ALONGSIDE the work
it governs instead of silently dropping it (the strict-ancestor reading also
made every `epic.*` condition NULL for epics, so even negated forms skipped
them).

Both consumers build this same CASE and differ only in how they bind the three
aliases: `service/queries.py` joins the chain once for a whole batch,
`slq/ancestors.py` correlates it per outer row. Keeping the arms here is what
stops the two from drifting apart again.
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
