"""Wire constants for approvals on workflow transitions (spec 71)."""

from enum import StrEnum


class ApprovalCheck(StrEnum):
    """The transition-rule check this plugin serves on the kernel's
    TRANSITION_CHECK socket (RADD-1383). Params: {"approvers": [{kind, id,
    name, required?}]} — EVERY entry must be satisfied."""

    REQUIRE_APPROVAL = "require_approval"


class ApprovalWidget(StrEnum):
    """The My Work widget this plugin contributes (RADD-1393) — the stored widget_type, and the
    `match` of the remote's `dashboard.widget` contribution that draws it. The value predates the
    contribution: layouts saved when dashboards hardcoded it keep working unchanged."""

    AWAITING = "approvals"


class ApproverKind(StrEnum):
    """One approver entry on a require_approval rule (spec 107): a USER must
    approve personally; a TEAM needs `required` approvals from current members."""

    USER = "user"
    TEAM = "team"


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
