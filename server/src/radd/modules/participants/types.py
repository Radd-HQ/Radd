"""Wire constants for request participants (spec 72)."""

from enum import StrEnum


class ParticipantEvent(StrEnum):
    # Emitted with entity_type=item DIRECTLY (csat/approvals precedent) so they
    # reach the item History feed, realtime item invalidation, and item-scoped
    # automations without an items RELATED_EVENT_TYPES entry.
    ADDED = "item.participant_added"
    REMOVED = "item.participant_removed"


class ParticipantEntity(StrEnum):
    PARTICIPANT = "item_participant"


#: RADD-1304: who may add and remove an issue's participants. Implied by
#: `item.update`; the Baseline holds it `@own` — a reporter shares their own
#: ticket — which was an identity check in code (`reporter_id == actor.id`)
#: until it became a grant an admin can see and revoke.
PARTICIPANT_MANAGE = "participant.manage"
