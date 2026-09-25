"""RADD-1299 — when is a target MET? One pure function per mode.

`evaluation.evaluate_items` gathers the facts once per batch (timelines,
public comment times, team members) and asks here per item and target. Pure,
so the modes are unit-tested without a database.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from radd.modules.comments.types import CommentOrigin

from .types import SlaMetOn


@dataclass(frozen=True)
class Stay:
    """One contiguous stay in a state (the reporting timeline's segment)."""

    state_id: uuid.UUID
    entered_at: datetime


def state_met_at(mode: SlaMetOn, state_ids: frozenset[str], stays: Sequence[Stay]) -> datetime | None:
    """ENTERS: the first stay in a chosen state. LEAVES: the first stay NOT in
    one — so an issue created outside them is met at creation, and one closed
    straight from Triage as Canceled is met at that move (the reason LEAVES
    exists beside ENTERS). First moment only: bouncing back does not reopen."""
    for stay in stays:
        inside = str(stay.state_id) in state_ids
        if (mode is SlaMetOn.ENTERS_STATES and inside) or (mode is SlaMetOn.LEAVES_STATES and not inside):
            return stay.entered_at
    return None


#: Comments that are never a human answer, whoever they are attributed to
#: (RADD-1318): the requester's own mail, and anything an automation wrote —
#: including under `act_as`, which is why the author cannot decide this.
NOT_A_RESPONSE = frozenset({CommentOrigin.INBOUND_MAIL.value, CommentOrigin.AUTOMATION.value})


def reply_met_at(
    replies: Sequence[tuple[uuid.UUID | None, datetime, str | None]],
    reporter_id: uuid.UUID | None,
    responders: frozenset[uuid.UUID] | None,
) -> datetime | None:
    """The first public reply (oldest first) by someone who counts: never the
    reporter, never inbound mail or an automation (by ORIGIN, RADD-1318 — it was
    "not the SYSTEM user", which an `act_as` automation passed); `responders`
    None = anyone else, otherwise only those people."""
    for author_id, at, origin in replies:
        if author_id is None or author_id == reporter_id or origin in NOT_A_RESPONSE:
            continue
        if responders is not None and author_id not in responders:
            continue
        return at
    return None
