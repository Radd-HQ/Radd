"""Wire constants for approvals on workflow transitions (spec 71)."""

from enum import StrEnum


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"  # enough approve votes — a banked unlock until consumed
    DECLINED = "declined"  # any decline is terminal for the request
    CANCELED = "canceled"  # withdrawn by the requester or a project manager
    APPLIED = "applied"  # the approved move happened — the unlock is spent


# Statuses that block a second request for the same (item, to_state).
LIVE_STATUSES: tuple[ApprovalStatus, ...] = (
    ApprovalStatus.PENDING,
    ApprovalStatus.APPROVED,
)


class ApprovalVerdict(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"


class ApprovalEvent(StrEnum):
    # All emitted with entity_type=item (csat/sla precedent) so they land in the
    # item History feed, realtime invalidation, and item-scoped automations.
    REQUESTED = "approval.requested"
    VOTED = "approval.voted"
    APPROVED = "approval.approved"
    DECLINED = "approval.declined"
    CANCELED = "approval.canceled"


class ApprovalEntity(StrEnum):
    REQUEST = "approval_request"


# Note length caps (request note + vote note).
NOTE_MAX_CHARS = 2000
