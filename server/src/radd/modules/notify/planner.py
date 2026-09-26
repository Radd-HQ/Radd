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

from .rules import OWN, Relation
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
    #: How this person is connected to the subject (spec 118) — only the planner
    #: still knows which set someone came out of.
    relation: Relation = OWN


@dataclass
class Plan:
    watch: set[uuid.UUID] = field(default_factory=set)
    notifications: list[PlannedNotification] = field(default_factory=list)

    def _add(
        self,
        user_id: uuid.UUID,
        type_: NotificationType,
        detail: dict,
        relation: Relation = OWN,
    ) -> None:
        if any(planned.user_id == user_id for planned in self.notifications):
            return  # precedence: first plan wins (personal types are added first)
        self.notifications.append(PlannedNotification(user_id, type_, detail, relation))

    def follow(self, user_id: uuid.UUID | None) -> None:
        """Auto-watch someone — never the system actor (RADD-996).

        Every planned watch goes through here because the exclusion belongs to
        the identity: mail intake creates items and replies AS the system actor,
        which can be creator, assignee or reporter. Kept out of
        `service.add_watchers`, which importers call verbatim."""
        if user_id is None or user_id == SYSTEM_ACTOR_ID:
            return
        self.watch.add(user_id)


@dataclass(frozen=True)
class Audience:
    """Everyone an AMBIENT notification could reach, split by relation — the
    fan-out is the only place that still knows which set someone came from. A
    person may be in several; the resolver's order settles it."""

    #: Assignee or reporter — the work is theirs.
    own: frozenset[uuid.UUID] = frozenset()
    #: Watcher, direct participant, or a member of a participant team.
    participating: frozenset[uuid.UUID] = frozenset()
    #: A member of the team the item is filed against (the my-teams column).
    in_my_teams: frozenset[uuid.UUID] = frozenset()
    #: Holds a project/space/team subscription naming this item's scope.
    subscribers: frozenset[uuid.UUID] = frozenset()

    def relation_of(self, user_id: uuid.UUID) -> Relation:
        return Relation(
            is_own=user_id in self.own,
            is_participating=user_id in self.participating,
            in_my_teams=user_id in self.in_my_teams,
        )

    def everyone(self) -> list[uuid.UUID]:
        """All of them, SORTED: `Plan._add` is first-wins, so set order would make
        plans differ between processes."""
        return sorted(self.own | self.participating | self.in_my_teams | self.subscribers)


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
    audience: Audience = Audience(),
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
    # Spec 118: an issue being FILED reached only its assignee, so "tell me what
    # is arriving in this project" was inexpressible. Planned LAST so the
    # assignee still hears "assigned to you" rather than "filed".
    for user_id in audience.everyone():
        if user_id != actor_id:
            plan._add(
                user_id, NotificationType.CREATED, {}, audience.relation_of(user_id)
            )
    return plan


def plan_item_updated(
    payload: dict,
    actor_id: uuid.UUID | None,
    audience: Audience,
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
        for user_id in audience.everyone():
            if user_id != actor_id:
                plan._add(
                    user_id,
                    NotificationType.STATE_CHANGED,
                    detail,
                    audience.relation_of(user_id),
                )
    # Spec 118's catch-all for any other field. Planned last: first-wins gives
    # anyone already named the more specific type.
    fields = sorted(name for name in changes if name)
    if fields:
        for user_id in audience.everyone():
            if user_id != actor_id:
                plan._add(
                    user_id,
                    NotificationType.UPDATED,
                    {"fields": fields},
                    audience.relation_of(user_id),
                )
    return plan


def plan_sla_breached(
    assignee_id: uuid.UUID | None,
    audience: Audience,
    detail: dict,
    type_: NotificationType = NotificationType.SLA_BREACH,
) -> Plan:
    """A breach — or a spec-69 due-soon warning (`type_=SLA_DUE_SOON`) — alerts
    the assignee first, then everyone else the item reaches (no actor — the SLA
    engine is a clock, nobody 'did' this)."""
    plan = Plan()
    if assignee_id is not None:
        plan._add(assignee_id, type_, detail, audience.relation_of(assignee_id))
    for user_id in audience.everyone():
        plan._add(user_id, type_, detail, audience.relation_of(user_id))
    return plan


def plan_subject_event(
    type_: NotificationType | str,
    actor_id: uuid.UUID | None,
    audience: Audience,
    detail: dict | None = None,
) -> Plan:
    """A non-item subject's own event — a page created or edited (spec 118; the
    kind comes from the subject's provider). No personal half and no watch: the
    provider's module follows on its own write path (RADD-719)."""
    plan = Plan()
    for user_id in audience.everyone():
        if user_id != actor_id:
            plan._add(user_id, type_, dict(detail or {}), audience.relation_of(user_id))
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
    """RADD-978: the added USER only — a team add plans nothing (team rows
    resolve live and are ambient). No `watch`: `add_participant` already
    auto-watched."""
    plan = Plan()
    user = payload.get("user") or {}
    user_id = uuid.UUID(user["id"]) if user.get("id") else None
    if user_id is not None and user_id != actor_id:
        plan._add(user_id, NotificationType.PARTICIPANT_ADDED, {})
    return plan


def plan_comment_created(
    payload: dict,
    actor_id: uuid.UUID | None,
    audience: Audience,
    mention_ids: frozenset[uuid.UUID],
    *,
    follow_actor: bool = True,
    comment_id: str | None = None,
) -> Plan:
    """A comment on an issue or a page (spec 118). `comment_id` rides each row
    so links land on the comment (RADD-1297); `follow_actor=False` for a page
    (`item_watchers` is keyed by item)."""
    plan = Plan()
    if follow_actor:
        plan.follow(actor_id)
    excerpt = payload.get("excerpt", "")
    visibility = payload.get("visibility", "public")
    located = {"comment_id": comment_id} if comment_id else {}
    # RADD-1391: an internal comment narrowed to teams (spec 50) carries them into
    # every row it plans — the consumer's team check reads THIS, and without it
    # every internal reader got the excerpt in their inbox.
    if payload.get("visible_to_teams"):
        located["visible_to_teams"] = list(payload["visible_to_teams"])
    for user_id in mention_ids:
        if user_id != actor_id:
            plan._add(
                user_id,
                NotificationType.MENTIONED,
                {"source": "comment", "excerpt": excerpt, "visibility": visibility, **located},
            )
    for user_id in audience.everyone():
        if user_id != actor_id:
            plan._add(
                user_id,
                NotificationType.COMMENTED,
                {"excerpt": excerpt, "visibility": visibility, **located},
                audience.relation_of(user_id),
            )
    return plan
