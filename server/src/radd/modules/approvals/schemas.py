import uuid

from pydantic import BaseModel, Field

from radd.apitypes import UtcDatetime

from .types import NOTE_MAX_CHARS, ApprovalStatus, ApprovalVerdict


class ApprovalRequestCreate(BaseModel):
    to_state_id: uuid.UUID
    note: str = Field(default="", max_length=NOTE_MAX_CHARS)


class ApprovalVoteCreate(BaseModel):
    verdict: ApprovalVerdict
    note: str = Field(default="", max_length=NOTE_MAX_CHARS)


class ApprovalUserRef(BaseModel):
    id: uuid.UUID
    name: str


class ApprovalVoteRead(BaseModel):
    user: ApprovalUserRef
    verdict: ApprovalVerdict
    note: str
    created_at: UtcDatetime


class ApprovalEntryRead(BaseModel):
    """Per-entry progress (spec 107): a USER entry needs that person's approval
    (required = 1); a TEAM entry needs `required` approvals from its CURRENT
    members. A request approves when EVERY entry is satisfied."""

    kind: str  # ApproverKind wire value: "user" | "team"
    id: uuid.UUID
    name: str  # snapshot display name (from the rule)
    required: int
    approved_count: int
    satisfied: bool


class ApprovalRequestRead(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    to_state_id: uuid.UUID
    to_state_name: str
    status: ApprovalStatus
    note: str
    requested_by: ApprovalUserRef | None
    # Per-entry rules + progress — the card's primary display (spec 107).
    entries: list[ApprovalEntryRead]
    # The CURRENT electorate, resolved server-side (entry users ∪ live team
    # members) — the client never re-derives team membership.
    approvers: list[ApprovalUserRef]
    approved_count: int
    votes: list[ApprovalVoteRead]
    created_at: UtcDatetime


class RequestableState(BaseModel):
    state_id: uuid.UUID
    name: str


class ItemApprovalsRead(BaseModel):
    """`GET /items/{id}/approvals` — the issue rail's Approvals card source.

    `live` = pending/approved requests (one per target state at most);
    `requestable_to_states` = targets an approval rule gates from the item's
    CURRENT state that have no live request yet (computed server-side — no
    failure-string matching in the client)."""

    live: list[ApprovalRequestRead]
    history: list[ApprovalRequestRead]
    requestable_to_states: list[RequestableState]


class VoteResult(BaseModel):
    """`POST /approvals/{id}/vote` — `errors` carries the OTHER guards' failures
    when the deciding approve could not auto-apply (banked unlock, spec 71 §4)."""

    request: ApprovalRequestRead
    applied: bool
    errors: list[str]


class PendingApprovalRead(BaseModel):
    """One row of `GET /approvals/pending` — the My Work queue."""

    id: uuid.UUID
    item_id: uuid.UUID
    item_key: str
    item_title: str
    to_state_name: str
    requested_by: ApprovalUserRef | None
    note: str
    created_at: UtcDatetime
