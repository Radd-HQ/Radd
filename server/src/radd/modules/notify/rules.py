"""Pure channel resolution — no I/O, unit-tested in `tests/test_notify_rules.py`.

Given one recipient's rule rows, the kind of thing that happened, and how that
person is CONNECTED to it, decide whether it reaches their inbox, their mailbox,
both, or neither. The consumer supplies the connection; this file supplies the
policy, on the same split `planner.py` already uses for who-gets-told.

## Most specific wins, with sparse fall-through

The scopes are consulted in this order, skipping any that does not apply:

    own  >  participating  >  a subscription to the item's TEAM
         >  my-teams  >  a subscription to its PROJECT  >  … to its SPACE

The first rule row that has an OPINION about this kind decides. A row is sparse
on purpose: subscribing to a project to hear about new issues should not also
overwrite what you had said about comments on your own work.

If nobody has an opinion, the FIRST APPLICABLE scope's default answers — not the
last, and not a global default. That is what makes "I subscribed to a project"
mean "and everything else about my own issues is unchanged".

## The defaults reproduce RADD-686 exactly

`DEFAULT_MATRIX` is the acceptance bar of this whole spec: a user with ZERO rule
rows must behave precisely as they did before it — every kind in the inbox, the
personally-directed five also mailed as they happen, the rest left to the digest.
That is asserted directly rather than described, because "we did not change
anything for people who did not ask" is the promise a preferences rewrite is
most likely to break and least likely to be caught breaking.

The three kinds spec 118 ADDED (`created`, `updated`, `page_created`) are `off`
in every relationship scope, and every subscription scope defaults to `off`
outright. So the only way to receive something new is to have asked for it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .kinds import SUBSCRIPTION_ONLY_KINDS, every_kind, is_personal
from .types import (
    DEFAULT_EMAIL_TYPES,
    RELATIONSHIP_SCOPES,
    Channel,
    NotificationType,
    RuleScope,
)


@dataclass(frozen=True)
class RuleRow:
    """One `notification_rules` row, flattened so the resolver stays pure.

    A projection rather than the ORM object: `resolve` is called once per planned
    notification inside the consumer's batch, and a dataclass with a plain dict
    cannot lazy-load anything against a session that may already have moved on.
    """

    scope: RuleScope
    scope_id: uuid.UUID | None
    channels: Mapping[str, str]


@dataclass(frozen=True)
class Subject:
    """What the event was ABOUT — the ids a subscription can name.

    Shared by every recipient of one event, which is why it is separate from
    `Relation`: the consumer resolves it once per event and the per-person part
    stays three booleans.
    """

    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    space_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Relation:
    """How ONE person is connected to that subject.

    `is_participating` is deliberately broad — a watcher, a direct participant,
    a member of a participant team, or someone the text named. They are one
    thing from the reader's point of view ("I am in this conversation") and
    splitting them would mean four columns nobody could tell apart.
    """

    is_own: bool = False
    is_participating: bool = False
    #: The item's team is one of this person's teams (the my-teams column).
    in_my_teams: bool = False


#: The relation a producer means when it addresses a person directly — an
#: automation's `notify_user`, or any future caller of `create_notification`
#: that has a recipient rather than an audience. Every such kind is personal, so
#: this is what `create_notification` assumes when nobody says otherwise.
OWN = Relation(is_own=True)


@dataclass(frozen=True)
class Verdict:
    """The answer, plus WHERE it came from — the settings page shows the source
    under an inherited cell, and "why am I getting this" is the question a
    notification preference exists to answer."""

    channel: Channel
    #: The scope that decided, or None when nothing applied at all.
    scope: RuleScope | None
    #: True when a default answered rather than a rule the person saved.
    inherited: bool = False

    @property
    def inbox(self) -> bool:
        return self.channel.inbox

    @property
    def email(self) -> bool:
        return self.channel.email

    @property
    def silent(self) -> bool:
        return self.channel.silent


SILENT = Verdict(Channel.OFF, None, inherited=True)


def _relationship_default(kind: NotificationType) -> Channel:
    """RADD-686's behaviour, stated as a cell value.

    Inbox for everything that existed then; email as well for the
    personally-directed set. The three kinds spec 118 added are off, because
    they had no behaviour to reproduce.
    """
    if kind in SUBSCRIPTION_ONLY_KINDS:
        return Channel.OFF
    return Channel.BOTH if kind in DEFAULT_EMAIL_TYPES else Channel.INBOX


def _all_off() -> dict[NotificationType, Channel]:
    return {kind: Channel.OFF for kind in every_kind()}


#: Per-scope defaults for every kind — total, so the fall-through always lands.
#:
#: `own` and `participating` are identical, and that is not laziness: RADD-686's
#: preference was per-TYPE with no notion of relation, so the mailer gave a
#: watcher and an assignee the same answer. Splitting them here would change
#: behaviour for people who never asked for anything, which is the one thing
#: this rewrite promised not to do. The columns exist so they CAN be told apart
#: from now on.
#:
#: `teams` is off: a member of the team an issue is filed against received
#: nothing before, and migrating everyone into a live subscription to their
#: whole team's traffic is a way to make a notification system hated in one
#: deploy.
DEFAULT_MATRIX: dict[RuleScope, dict[NotificationType, Channel]] = {
    RuleScope.OWN: {kind: _relationship_default(kind) for kind in every_kind()},
    RuleScope.PARTICIPATING: {kind: _relationship_default(kind) for kind in every_kind()},
    RuleScope.TEAMS: _all_off(),
    RuleScope.PROJECT: _all_off(),
    RuleScope.SPACE: _all_off(),
    RuleScope.TEAM: _all_off(),
}


@dataclass(frozen=True)
class RuleSet:
    """One person's rules, indexed for lookup. Built once per recipient set."""

    rows: tuple[RuleRow, ...] = ()
    _by_key: dict[tuple[RuleScope, uuid.UUID | None], RuleRow] = field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    def of(cls, rows: Sequence[RuleRow]) -> RuleSet:
        return cls(tuple(rows), {(row.scope, row.scope_id): row for row in rows})

    def get(self, scope: RuleScope, scope_id: uuid.UUID | None = None) -> RuleRow | None:
        return self._by_key.get((scope, scope_id))


EMPTY = RuleSet.of(())


def applicable_scopes(
    rules: RuleSet, relation: Relation, subject: Subject
) -> tuple[tuple[RuleScope, uuid.UUID | None], ...]:
    """The scopes that reach this person for this event, most specific first.

    A relationship scope applies when the relationship holds. A SUBSCRIPTION
    scope applies only when the person actually holds a row naming that project,
    space or team — an unsubscribed project is not a scope with an empty
    opinion, it is not a scope at all, which is what keeps its `off` default
    from swallowing the `participating` answer underneath it.
    """
    order: list[tuple[RuleScope, uuid.UUID | None]] = []
    if relation.is_own:
        order.append((RuleScope.OWN, None))
    if relation.is_participating:
        order.append((RuleScope.PARTICIPATING, None))
    if subject.team_id is not None and rules.get(RuleScope.TEAM, subject.team_id):
        order.append((RuleScope.TEAM, subject.team_id))
    if relation.in_my_teams:
        order.append((RuleScope.TEAMS, None))
    if subject.project_id is not None and rules.get(RuleScope.PROJECT, subject.project_id):
        order.append((RuleScope.PROJECT, subject.project_id))
    if subject.space_id is not None and rules.get(RuleScope.SPACE, subject.space_id):
        order.append((RuleScope.SPACE, subject.space_id))
    return tuple(order)


def resolve(
    kind: NotificationType,
    rules: RuleSet = EMPTY,
    relation: Relation = OWN,
    subject: Subject = Subject(),
) -> Verdict:
    """Which channels this kind reaches this person through.

    Personal kinds ignore `relation` entirely — the event chose the recipient,
    so the `own` column is the only one that could be asked.
    """
    order: tuple[tuple[RuleScope, uuid.UUID | None], ...]
    if is_personal(kind):
        order = ((RuleScope.OWN, None),)
    else:
        order = applicable_scopes(rules, relation, subject)
    for scope, scope_id in order:
        row = rules.get(scope, scope_id)
        if row is None:
            continue
        stored = row.channels.get(kind.value)
        if stored is None:
            continue
        try:
            return Verdict(Channel(stored), scope)
        except ValueError:
            # A channel value the enum does not know: a hand-written API call or
            # a member removed in a later version. Fall through to the next
            # scope rather than 500 in a background consumer — a preference that
            # cannot be parsed is a preference that was not expressed.
            continue
    if not order:
        return SILENT
    scope = order[0][0]
    return Verdict(DEFAULT_MATRIX[scope][kind], scope, inherited=True)


def default_channels(scope: RuleScope) -> dict[str, str]:
    """The scope's defaults as the wire map — what the settings page shows
    under an unset cell, so the SPA never carries a second copy of this table."""
    return {kind.value: channel.value for kind, channel in DEFAULT_MATRIX[scope].items()}


def relationship_defaults() -> dict[str, dict[str, str]]:
    """Every column's defaults, for the preferences read."""
    return {scope.value: default_channels(scope) for scope in RELATIONSHIP_SCOPES}
