"""In-transaction hook points this module dispatches (spec 119).

Distinct from `ItemEvent`, which is the OUTBOX vocabulary: those rows are read
after commit by consumers that notify, index and fan out. A hook handler runs
INSIDE the emitting transaction and can refuse the write — which is exactly what
intake validation needs and exactly what an outbox event cannot do.

The inversion is the point. `items` must never import `automations` (automations
already depends on items, and `tests/test_module_contracts.py` refuses the cycle),
so items DISPATCHES and whoever cares REGISTERS. Today that is one subscriber in
`automations`; with the plugin absent the dispatch is a no-op and creation is
byte-identical to what it was.
"""

from dataclasses import dataclass
from enum import StrEnum

from radd.modules.auth.models import User
from radd.modules.projects.models import Project

from .models import WorkItem


class ItemHook(StrEnum):
    """Hook points, named for the MOMENT rather than the fact.

    `item.creating`, present tense: the row exists and is flushed, nothing has
    been emitted yet, and a handler that raises un-creates it. Naming it
    `item.created` would have put it one letter from the outbox event and
    invited exactly the confusion this module cannot afford.
    """

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
