"""Pure notification planning — no I/O, unit-tested in tests/test_notify.py.

Given an event's payload plus pre-resolved context (watcher ids, resolved mention
ids), decide who gets notified and who gets auto-watched. The consumer wraps this
with DB lookups and permission filtering.

Invariants encoded here:
- The actor is never notified about their own action.
- One notification per user per event — precedence: assigned/mentioned (personal)
  beat state_changed/commented (ambient watching).
"""

import uuid
from dataclasses import dataclass, field

from .types import MENTION_EMAIL_RE, MENTION_TOKEN_RE, NotificationType


@dataclass(frozen=True)
class PlannedNotification:
    user_id: uuid.UUID
    type: NotificationType
    detail: dict  # merged into the stored payload (excerpt, from/to, source…)


@dataclass
class Plan:
    watch: set[uuid.UUID] = field(default_factory=set)
    notifications: list[PlannedNotification] = field(default_factory=list)

    def _add(self, user_id: uuid.UUID, type_: NotificationType, detail: dict) -> None:
        if any(planned.user_id == user_id for planned in self.notifications):
            return  # precedence: first plan wins (personal types are added first)
        self.notifications.append(PlannedNotification(user_id, type_, detail))


def parse_mention_candidates(text: str) -> tuple[set[str], set[str]]:
    """Raw mention candidates in a text: (uuid strings, lowercased emails).
    Candidates are unvalidated — the consumer resolves them against real users."""
    ids = {match.group("id").lower() for match in MENTION_TOKEN_RE.finditer(text or "")}
    emails = {match.group("email").lower() for match in MENTION_EMAIL_RE.finditer(text or "")}
    return ids, emails


def _assignee_id(payload: dict) -> uuid.UUID | None:
    assignee = payload.get("assignee")
    return uuid.UUID(assignee["id"]) if assignee else None


def _reporter_id(payload: dict) -> uuid.UUID | None:
    reporter = payload.get("reporter")
    return uuid.UUID(reporter["id"]) if reporter else None


def plan_item_created(
    payload: dict,
    actor_id: uuid.UUID | None,
    mention_ids: frozenset[uuid.UUID],
) -> Plan:
    plan = Plan()
    if actor_id is not None:
        plan.watch.add(actor_id)
    assignee = _assignee_id(payload)
    if assignee is not None:
        plan.watch.add(assignee)
        if assignee != actor_id:
            plan._add(assignee, NotificationType.ASSIGNED, {})
    # Spec 62: the reporter auto-watches what they raised — updates and replies
    # then reach them through the ordinary watcher machinery (watch, no ping).
    reporter = _reporter_id(payload)
    if reporter is not None:
        plan.watch.add(reporter)
    for user_id in mention_ids:
        if user_id != actor_id:
            plan._add(user_id, NotificationType.MENTIONED, {"source": "description"})
    return plan


def plan_item_updated(
    payload: dict,
    actor_id: uuid.UUID | None,
    watcher_ids: frozenset[uuid.UUID],
    mention_ids: frozenset[uuid.UUID],
) -> Plan:
    plan = Plan()
    changes = {change["field"]: change for change in payload.get("changes", [])}
    if "assignee" in changes:
        assignee = _assignee_id(payload)
        if assignee is not None:
            plan.watch.add(assignee)
            if assignee != actor_id:
                plan._add(assignee, NotificationType.ASSIGNED, {})
    # Spec 62: re-filing on someone's behalf — the NEW reporter starts watching.
    if "reporter" in changes:
        reporter = _reporter_id(payload)
        if reporter is not None:
            plan.watch.add(reporter)
    if "description" in changes:
        for user_id in mention_ids:
            if user_id != actor_id:
                plan._add(user_id, NotificationType.MENTIONED, {"source": "description"})
    if "state" in changes:
        change = changes["state"]
        detail = {"from": change.get("from"), "to": change.get("to")}
        for user_id in watcher_ids:
            if user_id != actor_id:
                plan._add(user_id, NotificationType.STATE_CHANGED, detail)
    return plan


def plan_sla_breached(
    assignee_id: uuid.UUID | None,
    watcher_ids: frozenset[uuid.UUID],
    detail: dict,
    type_: NotificationType = NotificationType.SLA_BREACH,
) -> Plan:
    """A breach — or a spec-69 due-soon warning (`type_=SLA_DUE_SOON`) — alerts
    the assignee first, then every watcher (no actor — the SLA engine is a
    clock, nobody 'did' this)."""
    plan = Plan()
    if assignee_id is not None:
        plan._add(assignee_id, type_, detail)
    for user_id in watcher_ids:
        plan._add(user_id, type_, detail)
    return plan


def plan_approval_requested(
    payload: dict,
    actor_id: uuid.UUID | None,
    approver_ids: frozenset[uuid.UUID],
) -> Plan:
    """Spec 71: each eligible approver gets a ping; approvers are deliberately
    NOT auto-watched — their involvement ends with the vote."""
    plan = Plan()
    detail = {
        "action": "requested",
        "to_state": payload.get("to_state"),
        # Spec 107: the rule summary string ("Hussein Jarrar; 2 of DevOps").
        "approvers": payload.get("approvers_summary"),
    }
    for user_id in approver_ids:
        if user_id != actor_id:
            plan._add(user_id, NotificationType.APPROVAL, detail)
    return plan


def plan_approval_decided(
    payload: dict,
    actor_id: uuid.UUID | None,
    requester_id: uuid.UUID | None,
    action: str,
) -> Plan:
    """Spec 71: approved/declined pings the requester (never the deciding voter
    about their own vote)."""
    plan = Plan()
    if requester_id is not None and requester_id != actor_id:
        plan._add(
            requester_id,
            NotificationType.APPROVAL,
            {
                "action": action,
                "to_state": payload.get("to_state"),
                "approved_count": payload.get("approved_count"),
                "approvers": payload.get("approvers_summary"),
            },
        )
    return plan


def plan_comment_created(
    payload: dict,
    actor_id: uuid.UUID | None,
    watcher_ids: frozenset[uuid.UUID],
    mention_ids: frozenset[uuid.UUID],
) -> Plan:
    plan = Plan()
    if actor_id is not None:
        plan.watch.add(actor_id)
    excerpt = payload.get("excerpt", "")
    visibility = payload.get("visibility", "public")
    for user_id in mention_ids:
        if user_id != actor_id:
            plan._add(
                user_id,
                NotificationType.MENTIONED,
                {"source": "comment", "excerpt": excerpt, "visibility": visibility},
            )
    for user_id in watcher_ids:
        if user_id != actor_id:
            plan._add(
                user_id,
                NotificationType.COMMENTED,
                {"excerpt": excerpt, "visibility": visibility},
            )
    return plan
