"""Pure notification planning — no I/O, unit-tested in tests/test_notify.py.

Given an event's payload plus pre-resolved context (watcher ids, resolved mention
ids), decide who gets notified and who gets auto-watched. The consumer wraps this
with DB lookups and permission filtering.

Invariants encoded here:
- The actor is never notified about their own action.
- One notification per user per event — precedence: assigned/mentioned (personal)
  beat state_changed/commented (ambient watching).
- The system actor is never auto-watched (RADD-996 — see `Plan.follow`).
"""

import uuid
from dataclasses import dataclass, field

from .types import (
    MENTION_EMAIL_RE,
    MENTION_TOKEN_RE,
    SYSTEM_ACTOR_ID,
    NotificationType,
)


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

    def follow(self, user_id: uuid.UUID | None) -> None:
        """Auto-watch someone — unless they are not a someone (RADD-996).

        EVERY watch this file plans goes through here, because the exclusion is a
        property of the identity rather than of the moment it appears: the system
        actor can be a creator, an assignee or a reporter, and a guard written at
        one of those three would be a guard missing at the other two.

        Mail intake creates its items and posts its reply comments AS the system
        actor, so auto-watching the creator put `automation@radd.system` on the
        watcher list of every ticket that has ever arrived by email — and each
        human reply then fanned a `commented` notification out to a robot, which
        the mailer dutifully tried to deliver to an address that does not
        receive. `mailintake.outbound` has excluded the same actor from its own
        recipients since spec 62; this is the other half of that rule.

        The guard is here rather than in `service.add_watchers` on purpose. That
        function is a dumb idempotent write with two other callers — jiraimport
        restores a source system's watcher list through it verbatim — and WHO
        should follow an issue is a planning question. Deciding it in the writer
        would put policy where two unrelated callers inherit it silently.
        """
        if user_id is None or user_id == SYSTEM_ACTOR_ID:
            return
        self.watch.add(user_id)


def parse_mention_candidates(text: str) -> tuple[set[str], set[str]]:
    """Raw mention candidates in a text: (uuid strings, lowercased emails).
    Candidates are unvalidated — the consumer resolves them against real users."""
    ids = {match.group("id").lower() for match in MENTION_TOKEN_RE.finditer(text or "")}
    emails = {match.group("email").lower() for match in MENTION_EMAIL_RE.finditer(text or "")}
    return ids, emails


def _assignee_id(payload: dict) -> uuid.UUID | None:
    assignee = (payload.get("item") or {}).get("assignee")
    return uuid.UUID(assignee["id"]) if assignee else None


def _reporter_id(payload: dict) -> uuid.UUID | None:
    reporter = (payload.get("item") or {}).get("reporter")
    return uuid.UUID(reporter["id"]) if reporter else None


def plan_item_created(
    payload: dict,
    actor_id: uuid.UUID | None,
    mention_ids: frozenset[uuid.UUID],
) -> Plan:
    plan = Plan()
    plan.follow(actor_id)
    assignee = _assignee_id(payload)
    if assignee is not None:
        plan.follow(assignee)
        if assignee != actor_id:
            plan._add(assignee, NotificationType.ASSIGNED, {})
    # Spec 62: the reporter auto-watches what they raised — updates and replies
    # then reach them through the ordinary watcher machinery (watch, no ping).
    plan.follow(_reporter_id(payload))
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
            plan.follow(assignee)
            if assignee != actor_id:
                plan._add(assignee, NotificationType.ASSIGNED, {})
    # Spec 62: re-filing on someone's behalf — the NEW reporter starts watching.
    if "reporter" in changes:
        plan.follow(_reporter_id(payload))
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


def plan_participant_added(payload: dict, actor_id: uuid.UUID | None) -> Plan:
    """RADD-978: being shared into an issue tells the person it happened.

    Exactly ONE recipient — the added USER, from the event's `user` ref. A TEAM
    add plans nothing: a team row resolves to CURRENT members at fan-out time
    (that is what makes joining a team join its shared tickets), so there is no
    stable set to address, and the membership is ambient rather than personally
    directed. Someone who adds themself hears nothing, like every other type.

    No `watch` entry: `participants.add_participant` already auto-watched the
    direct user through `notify.add_watchers` on the write path. Adding it here
    too would be a second mechanism agreeing by luck.
    """
    plan = Plan()
    user = payload.get("user") or {}
    user_id = uuid.UUID(user["id"]) if user.get("id") else None
    if user_id is not None and user_id != actor_id:
        plan._add(user_id, NotificationType.PARTICIPANT_ADDED, {})
    return plan


def plan_comment_created(
    payload: dict,
    actor_id: uuid.UUID | None,
    watcher_ids: frozenset[uuid.UUID],
    mention_ids: frozenset[uuid.UUID],
) -> Plan:
    plan = Plan()
    plan.follow(actor_id)
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
