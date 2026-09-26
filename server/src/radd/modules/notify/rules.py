"""Pure channel resolution — no I/O, unit-tested in `tests/test_notify_rules.py`.

Given one recipient's rule rows, the kind, and how that person is CONNECTED to
the subject, decide inbox / email / both / neither.

Scopes are consulted most-specific first, skipping any that does not apply:
own > participating > TEAM subscription > my-teams > PROJECT > SPACE.
The first row with an opinion about the kind decides; rows are sparse, so a
project subscription never overwrites what you said about your own work. With
no opinion anywhere, the FIRST applicable scope's default answers.

Defaults reproduce RADD-686's channels for everyone the old fan-out reached.
The audience is deliberately wider: `own` holds assignee + reporter whether or
not they watch, so Unwatch no longer silences an assignee, and imported items
(no auto-watch rows) now reach their assignees. `test_notify_scoped_fanout.py`
pins both. Spec 118's new kinds and every subscription scope default to `off`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .kinds import every_kind, is_personal, spec_for
from .types import RELATIONSHIP_SCOPES, Channel, RuleScope


@dataclass(frozen=True)
class RuleRow:
    """One `notification_rules` row, flattened: a plain projection cannot
    lazy-load against a session that has moved on."""

    scope: RuleScope
    scope_id: uuid.UUID | None
    channels: Mapping[str, str]


@dataclass(frozen=True)
class Subject:
    """What the event was ABOUT — the ids a subscription can name. Resolved once
    per event; `Relation` is the per-person part."""

    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    space_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Relation:
    """How ONE person is connected to that subject. `is_participating` is
    deliberately broad: watcher, participant, participant-team member or someone
    the text named are one thing to the reader ("I am in this conversation")."""

    is_own: bool = False
    is_participating: bool = False
    #: The item's team is one of this person's teams (the my-teams column).
    in_my_teams: bool = False


#: The relation a producer means when it addresses a person directly (an
#: automation's `notify_user`) — `create_notification`'s default.
OWN = Relation(is_own=True)


@dataclass(frozen=True)
class Verdict:
    """The answer, plus WHERE it came from ("why am I getting this")."""

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


def _relationship_default(kind: str) -> Channel:
    """The kind's own `default_channel` (RADD-1326), so a plugin's kind carries
    its default with it; an undeclared kind degrades to the inbox."""
    spec = spec_for(kind)
    if spec is not None:
        try:
            return Channel(spec.default_channel)
        except ValueError:
            return Channel.INBOX
    return Channel.INBOX


def _all_off() -> dict[str, Channel]:
    return {kind: Channel.OFF for kind in every_kind()}


def default_matrix() -> dict[RuleScope, dict[str, Channel]]:
    """Per-scope defaults for every kind (a function: plugin kinds register after
    import). `own` == `participating` on purpose — RADD-686 had no relation, so
    a split would change behaviour nobody asked for. `teams` and every
    subscription scope default to `off`."""
    relationship = {kind: _relationship_default(kind) for kind in every_kind()}
    return {
        RuleScope.OWN: dict(relationship),
        RuleScope.PARTICIPATING: dict(relationship),
        RuleScope.TEAMS: _all_off(),
        RuleScope.PROJECT: _all_off(),
        RuleScope.SPACE: _all_off(),
        RuleScope.TEAM: _all_off(),
    }


def _default_for(scope: RuleScope, kind: str) -> Channel:
    """This scope's default for `kind`, degrading instead of raising for a kind
    with no vocabulary row (RADD-978/1056: a KeyError inside the consumer's
    SAVEPOINT silently dropped the notification). Unreachable while
    `test_notify_rules` holds the vocabulary equal to the enum."""
    known = default_matrix()[scope]
    if str(kind) in known:
        return known[str(kind)]
    return _relationship_default(kind) if scope in RELATIONSHIP_SCOPES else Channel.OFF


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
    A subscription scope applies only when the person holds a row naming it —
    an unsubscribed project is not a scope at all, or its `off` default would
    swallow the `participating` answer underneath it."""
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
    kind: str,
    rules: RuleSet = EMPTY,
    relation: Relation = OWN,
    subject: Subject = Subject(),
) -> Verdict:
    """Which channels this kind reaches this person through. Personal kinds
    ignore `relation`: the event chose the recipient, so only `own` is asked."""
    order: tuple[tuple[RuleScope, uuid.UUID | None], ...]
    if is_personal(kind):
        order = ((RuleScope.OWN, None),)
    else:
        order = applicable_scopes(rules, relation, subject)
    for scope, scope_id in order:
        row = rules.get(scope, scope_id)
        if row is None:
            continue
        stored = row.channels.get(str(kind))
        if stored is None:
            continue
        try:
            return Verdict(Channel(stored), scope)
        except ValueError:
            # An unknown channel value falls through to the next scope rather
            # than 500 in a background consumer: unparseable = not expressed.
            continue
    if not order:
        return SILENT
    scope = order[0][0]
    return Verdict(_default_for(scope, kind), scope, inherited=True)
