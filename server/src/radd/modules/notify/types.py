"""Enums, wire constants, and the mention grammar for the notify module."""

import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from radd.kernel import NotificationChannel


class NotificationType(StrEnum):
    ASSIGNED = "assigned"
    MENTIONED = "mentioned"
    STATE_CHANGED = "state_changed"
    COMMENTED = "commented"
    SLA_BREACH = "sla_breach"
    SLA_DUE_SOON = "sla_due_soon"  # spec 69: the pre-breach warning
    AUTOMATION = "automation"  # spec 58b: payload {"message", "rule"}
    APPROVAL = "approval"  # spec 71: requests to approvers, decisions to the requester
    PAGE_UPDATED = "page_updated"  # RADD-719: no item; the payload carries the page
    # RADD-978: a USER was shared into an item; a team add plans nothing.
    PARTICIPANT_ADDED = "participant_added"
    # Spec 118: the AMBIENT kinds a subscription exists to deliver — `off` in
    # every relationship scope by default.
    CREATED = "created"
    UPDATED = "updated"
    PAGE_CREATED = "page_created"


class RuleScope(StrEnum):
    """How a person is connected to the thing an event is about (spec 118).

    OWN/PARTICIPATING/TEAMS are RELATIONSHIPS (`scope_id` NULL); PROJECT/SPACE/
    TEAM are SUBSCRIPTIONS naming a target. TEAMS follows my membership; TEAM is
    one named team I may not even be in.
    """

    OWN = "own"
    PARTICIPATING = "participating"
    TEAMS = "teams"
    PROJECT = "project"
    SPACE = "space"
    TEAM = "team"


#: The scopes that point at a row — `scope_id` is REQUIRED for these and
#: forbidden for the rest, which is the whole validity rule for a rule row.
SUBSCRIPTION_SCOPES: frozenset[RuleScope] = frozenset(
    {RuleScope.PROJECT, RuleScope.SPACE, RuleScope.TEAM}
)

#: The matrix's columns, in display order. A relationship scope always applies
#: when it holds, so these are the ones with a default worth stating.
RELATIONSHIP_SCOPES: tuple[RuleScope, ...] = (
    RuleScope.OWN,
    RuleScope.PARTICIPATING,
    RuleScope.TEAMS,
)


#: One matrix cell (spec 118). The vocabulary is the kernel's, because a contributed
#: `NotificationKindSpec.default_channel` names a member (RADD-1467); this is its name here.
Channel = NotificationChannel


# Wire strings for the slas module's timer events (specs 30/69). Constants, not
# imports — slas loads AFTER notify in RADD_MODULES; keep in sync with SlaEvent.
SLA_BREACHED_EVENT = "sla.breached"
SLA_DUE_SOON_EVENT = "sla.due_soon"

# Wire strings for the approvals module's lifecycle events (spec 71) — same
# idiom, approvals loads AFTER notify; keep in sync with ApprovalEvent.
APPROVAL_REQUESTED_EVENT = "approval.requested"
APPROVAL_APPROVED_EVENT = "approval.approved"
APPROVAL_DECLINED_EVENT = "approval.declined"

#: What notify stamps on a notification about a NON-ITEM subject (RADD-1385),
#: beside the provider's own display payload: which subject provider vouches
#: for the row, and the subject's id. The mail loops' read re-check asks that
#: provider again at send time, so a row names who can still answer for it.
SUBJECT_TYPE_KEY = "subject_type"
SUBJECT_ID_KEY = "subject_id"


@dataclass(frozen=True)
class SubjectRef:
    """A non-item subject, as a `NOTIFICATION_SUBJECT` provider locates it.

    `scope_id` is its CONTAINER — the id a subscription in the provider's scope
    names (a page's space). `payload` is what the notification row is written
    with, resolved at WRITE time so a later rename cannot make the row lie.
    """

    id: uuid.UUID
    scope_id: uuid.UUID | None = None
    payload: dict = field(default_factory=dict)


# participants' add event as a wire string (it loads after notify and is
# disableable; keep in sync with ParticipantEvent.ADDED). No REMOVE constant on
# purpose: nobody needs telling they stopped being copied in.
PARTICIPANT_ADDED_EVENT = "item.participant_added"

#: The engine's system actor, as a literal so `planner.py` stays import-free;
#: `test_notify.py` pins it equal to `automations.types.SYSTEM_ACTOR_ID`.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000a70a70")


class NotificationDelivery(StrEnum):
    """What the EMAIL channel did with a row (RADD-1457). `emailed_at` is set by
    SENT alone: it is the moment a transport accepted the message, never a
    bookkeeping stamp.

    * PENDING — not settled: never attempted, or waiting out a retry rung;
    * SENT — a transport accepted a message carrying it;
    * UNDELIVERABLE — no mail transport was live to carry it; retried while the
      row is younger than `notify_undeliverable_retry_hours` once one is registered;
    * DROPPED — the channel closed the row without a message and will not
      reopen it: read in the app first, past the age window, digest opted out,
      no mailbox, or refused past the retry ladder.
    """

    PENDING = "pending"
    SENT = "sent"
    UNDELIVERABLE = "undeliverable"
    DROPPED = "dropped"


class NotifyEvent(StrEnum):
    NOTIFICATION_CREATED = "notification.created"
    #: RADD-1457: a queued email had no transport to carry it (payload: user, kind).
    NOTIFICATION_UNDELIVERABLE = "notification.undeliverable"
    ITEM_WATCHED = "item.watched"
    ITEM_UNWATCHED = "item.unwatched"


class NotifyEntity(StrEnum):
    NOTIFICATION = "notification"
    WATCHER = "item_watcher"


# This module's cursor name in the events stream.
CONSUMER_NAME = "notify.consumer"

# @[Display Name](user-uuid) — the token the rich editor emits (spec 29).
MENTION_TOKEN_RE = re.compile(r"@\[[^\]\n]{1,120}\]\((?P<id>[0-9a-fA-F-]{36})\)")

# @user@example.com — a @-prefixed registered email, typeable from a plain textarea.
MENTION_EMAIL_RE = re.compile(r"@(?P<email>[\w.+-]+@[\w-]+\.[\w.-]+)")
