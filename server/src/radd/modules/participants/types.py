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


#: Who may add/remove an issue's participants; implied by item.update, held @own on the Baseline.
PARTICIPANT_MANAGE = "participant.manage"


#: RADD-1385: this plugin's provider name on the kernel NOTIFICATION_AUDIENCE socket.
TEAM_AUDIENCE = "participant_teams"
