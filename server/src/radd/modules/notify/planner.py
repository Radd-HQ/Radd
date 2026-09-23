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
    #: How this person is connected to the subject (spec 118) — planned here
    #: because THIS is where the recipient sets are distinguished. The consumer
    #: knows the ids; only the planner knows which set someone came out of, and
    #: recovering that afterwards would mean re-deriving what was just decided.
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


@dataclass(frozen=True)
class Audience:
    """Everyone an AMBIENT notification could reach, split by how they got here.

    Three sets, because the three answer differently in the matrix and the only
    place that still knows which set someone came out of is the fan-out that
    built them. Flattening this to one recipient list — which is what
    `recipient_ids` was before spec 118 — is precisely what makes "stop telling
    me about issues I merely watch, but keep telling me about mine" unsayable.

    A person may be in several: an assignee who also watches is `own` AND
    `participating`, and the resolver's ordering is what settles which of their
    answers applies.
    """

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
        """All of them, in a STABLE order.

        Sorted rather than set-ordered: `Plan._add` is first-wins, so iteration
        order decides which type a person in two sets ends up with, and a plan
        that depends on set iteration is a plan that differs between processes.
        """
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
    # Spec 118's catch-all: everything else that moved. An edit that changed
    # neither state nor description reached NOBODY before — a reprioritised,
    # relabelled, re-estimated issue was silent to everyone watching it.
    #
    # Planned last, so `Plan._add`'s first-wins gives the specific type to anyone
    # a specific type already named. That is also why turning "Any other edit" on
    # while leaving "State changes" off does not resurrect state changes: one
    # notification per person per event is the invariant, and the more specific
    # description of the event is the one that gets it.
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


def plan_page_event(
    type_: NotificationType,
    actor_id: uuid.UUID | None,
    audience: Audience,
    detail: dict | None = None,
) -> Plan:
    """A page was created or edited (spec 118).

    Wiki events have no personal half — nobody is "assigned" a page — so this is
    one loop, and the whole of the decision is which scope each recipient stands
    in. It plans no watch: `pages.update_page` auto-watches the editor on the
    write path (RADD-719), and a second mechanism agreeing by luck is how the two
    fan-outs this spec deleted came to disagree.
    """
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
    audience: Audience,
    mention_ids: frozenset[uuid.UUID],
    *,
    follow_actor: bool = True,
    comment_id: str | None = None,
) -> Plan:
    """A comment on an issue — or, since spec 118, on a PAGE.

    `comment_id` (RADD-1297) rides in every row's detail so the inbox and the
    mail can link to the COMMENT rather than the top of its issue or page.

    `follow_actor` is off for a page comment: `item_watchers` is keyed by item
    and a page has none, so auto-watching through this plan would try to write a
    watcher row against an id that is not an item. Commenting on a page does not
    subscribe you to it, which is a smaller promise than the issue path makes and
    the only one this table can keep.
    """
    plan = Plan()
    if follow_actor:
        plan.follow(actor_id)
    excerpt = payload.get("excerpt", "")
    visibility = payload.get("visibility", "public")
    located = {"comment_id": comment_id} if comment_id else {}
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
