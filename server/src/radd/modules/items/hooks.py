"""In-transaction hook points this module dispatches (spec 119).

Unlike `ItemEvent` (the outbox, read after commit), a hook handler runs INSIDE
the emitting transaction and may refuse the write — what intake validation
needs. `items` dispatches and `automations` registers, because items must never
import automations (tests/test_module_contracts.py refuses the cycle).
"""

from dataclasses import dataclass
from enum import StrEnum

from radd.modules.auth.models import User
from radd.modules.projects.models import Project

from .models import WorkItem


class ItemHook(StrEnum):
    """Named for the MOMENT: `item.creating` — the row is flushed, nothing is
    emitted yet, and a handler that raises un-creates it."""

    CREATING = "item.creating"


@dataclass(frozen=True)
class ItemCreating:
    """The subject of `ItemHook.CREATING`.

    The ACTOR rides along because a handler may need to answer a question about
    the person doing this, not only about the row: intake validation reads the
    draft through the automation's own identity, but it still has to know
    whether this write came from a person at all.
    """

    item: WorkItem
    project: Project
    actor: User
