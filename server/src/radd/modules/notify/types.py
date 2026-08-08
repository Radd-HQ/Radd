"""Enums, wire constants, and the mention grammar for the notify module."""

import re
import uuid
from enum import StrEnum


class NotificationType(StrEnum):
    ASSIGNED = "assigned"
    MENTIONED = "mentioned"
    STATE_CHANGED = "state_changed"
    COMMENTED = "commented"
    SLA_BREACH = "sla_breach"
    # Spec 69: the pre-breach sla.due_soon warning — muteable like the rest.
    SLA_DUE_SOON = "sla_due_soon"
    # Spec 58b: an automation rule's notify_user action — payload carries
    # {"message", "rule"} rendered from the rule's template.
    AUTOMATION = "automation"
    # Spec 71: approval requests (to each eligible approver) and decisions (to
    # the requester) — detail carries {"action", "to_state", ...}. Muteable.
    APPROVAL = "approval"
    # RADD-719: a watched wiki page changed. Carries no item — the payload
    # holds the page's slugs so the inbox row can link without a join.
    PAGE_UPDATED = "page_updated"
    # RADD-978: someone SHARED an item with you (spec 72's direct user
    # participant). The add auto-watches, so every LATER event reached them —
    # the add itself told nobody, which is the one moment they had no idea the
    # issue existed. A team add plans nothing personal: team rows resolve live
    # at fan-out and are ambient by design.
    PARTICIPANT_ADDED = "participant_added"


#: The types a user gets an EMAIL about the moment they happen, when they have
#: expressed no preference (RADD-686). No prefs row means exactly this set.
#:
#: The personally-directed, high-signal set: someone assigned you the work,
#: named you, replied to you, is waiting on your decision, or pulled you into an
#: issue (RADD-978). The ambient types (state changes on things you watch, SLA
#: timers, automation pings) stay in the digest by default, because an inbox that
#: mails everything is an inbox nobody reads. Every type is switchable per-user
#: either way — this is the default, not the rule — which is what the module
#: constant it replaces (RADD-968's hard-coded `{commented}`) could never be.
#:
#: **Known asymmetry (RADD-978, accepted).** `participant_added` was added to
#: this set AFTER `d686emailtypes` backfilled every existing `notification_prefs`
#: row with the four types this set then held. So a user who has ever saved a
#: preference does NOT get this one by email until they tick the box, while a
#: user with no row does — the default and the stored rows disagree by exactly
#: this type. No migration corrects it on purpose: rewriting a stored preference
#: to add a channel the person never asked for is worse than the inconsistency,
#: and the row is theirs to edit. Any type added here later inherits the same
#: rule — the default applies to people who have not spoken, not to everyone.
DEFAULT_EMAIL_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.ASSIGNED,
        NotificationType.MENTIONED,
        NotificationType.COMMENTED,
        NotificationType.APPROVAL,
        NotificationType.PARTICIPANT_ADDED,
    }
)


def default_email_types() -> list[NotificationType]:
    """`DEFAULT_EMAIL_TYPES` in NotificationType declaration order.

    A frozenset has no order, and the stored JSON array, the API response and
    the checkbox column all need one that does not shuffle between processes.
    """
    return [type_ for type_ in NotificationType if type_ in DEFAULT_EMAIL_TYPES]


def default_email_type_values() -> list[str]:
    """The same list as wire strings — what the column actually stores."""
    return [type_.value for type_ in default_email_types()]


# Wire strings for the slas module's timer events (specs 30/69). Constants, not
# imports — slas loads AFTER notify in RADD_MODULES; keep in sync with SlaEvent.
SLA_BREACHED_EVENT = "sla.breached"
SLA_DUE_SOON_EVENT = "sla.due_soon"

# Wire strings for the approvals module's lifecycle events (spec 71) — same
# idiom, approvals loads AFTER notify; keep in sync with ApprovalEvent.
APPROVAL_REQUESTED_EVENT = "approval.requested"
APPROVAL_APPROVED_EVENT = "approval.approved"
APPROVAL_DECLINED_EVENT = "approval.declined"

# Wire string for the participants module's add event (spec 72; RADD-978) — the
# same idiom again, participants loads AFTER notify (and is disableable); keep in
# sync with ParticipantEvent.ADDED. There is deliberately no constant for the
# REMOVE event: nobody needs telling they stopped being copied in.
PARTICIPANT_ADDED_EVENT = "item.participant_added"

#: The engine's system actor (`automations.types.SYSTEM_ACTOR_ID`) — the identity
#: every automated write carries, mail intake's items and comments included.
#:
#: A constant for a different reason than the three above: automations loads
#: BEFORE notify, so importing it would be legal. It stays a literal because
#: `planner.py` is pure policy with no `radd.modules` import at all, and because
#: one sentinel uuid is not worth a module edge on a dependency list that is
#: otherwise exactly the spine. `test_notify.py` asserts the two are the same
#: uuid, so this cannot drift — the risk the idiom above has always carried.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000a70a70")


class NotifyEvent(StrEnum):
    NOTIFICATION_CREATED = "notification.created"
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
