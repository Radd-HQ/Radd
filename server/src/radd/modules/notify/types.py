"""Enums, wire constants, and the mention grammar for the notify module."""

import re
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


# Wire strings for the slas module's timer events (specs 30/69). Constants, not
# imports — slas loads AFTER notify in RADD_MODULES; keep in sync with SlaEvent.
SLA_BREACHED_EVENT = "sla.breached"
SLA_DUE_SOON_EVENT = "sla.due_soon"

# Wire strings for the approvals module's lifecycle events (spec 71) — same
# idiom, approvals loads AFTER notify; keep in sync with ApprovalEvent.
APPROVAL_REQUESTED_EVENT = "approval.requested"
APPROVAL_APPROVED_EVENT = "approval.approved"
APPROVAL_DECLINED_EVENT = "approval.declined"


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
