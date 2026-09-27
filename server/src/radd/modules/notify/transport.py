"""The MAIL_TRANSPORT socket contract, from notify's side (RADD-1385).

Notify decides who is mailed what; a transport (today `mailintake`) carries it.
The shared vocabulary is notify's: `NotificationMailKind`, and what a failure
means to a retry ladder (`MailFailureReport`). No transport = no email: both
loops record pending rows UNDELIVERABLE, and a re-enabled mail plugin picks up
only the rows still inside `notify_undeliverable_retry_hours`, never a backlog.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from radd.kernel import sockets


class NotificationMailKind(StrEnum):
    """WHAT notify mailed, carried as `kind` on `mail.sent`/`mail.failed`
    (RADD-1318), so a rule on "Email sent" can tell a notification from the
    desk's reply to a customer."""

    NOTIFICATION = "notification"  # one notification mailed to a user
    DIGEST = "digest"  # a batch of notifications


class MailFailureReport(StrEnum):
    """What the transport does with a delivery failure (RADD-997/1036): REPORT
    emits `mail.failed` (the default — a one-shot send); SILENT emits nothing
    because a retry is coming; TERMINAL emits and marks it given up. Three values,
    not two booleans, so "silent AND terminal" is unsayable."""

    REPORT = "report"
    SILENT = "silent"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class NotificationMail:
    """One composed message. `item_id` set = thread on that issue (`comment_id`
    names the relayed comment); `headers` are notify's own and never override
    the thread's."""

    to_address: str
    to_name: str
    subject: str
    text: str
    html: str
    kind: NotificationMailKind
    failure: MailFailureReport = MailFailureReport.REPORT
    headers: Mapping[str, str] = field(default_factory=dict)
    item_id: uuid.UUID | None = None
    comment_id: uuid.UUID | None = None


def mail_transport() -> sockets.MailTransport | None:
    """The registered transport or None; read every tick (never cached) so a
    disable applies at once. MAIL_TRANSPORT is a single-provider socket: two
    transports raise (`AmbiguousProvider`) rather than one being picked."""
    return sockets.single_provider(sockets.Socket.MAIL_TRANSPORT)
