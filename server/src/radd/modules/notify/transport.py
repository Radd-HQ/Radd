"""The MAIL_TRANSPORT socket, from notify's side (RADD-1385).

Notify decides WHO is mailed WHAT; a transport carries it. `mailintake` is the
transport today — sender rows, threading on the item, `mail.sent`/`mail.failed`
— and it reaches notify through the kernel socket rather than notify importing
it. That import was the defect: plugin code is always importable, so notify
kept calling into a mail plugin the plugin manager had switched off.

The vocabulary the two sides share is notify's, because notify is what it
describes: WHICH notification email this is (`NotificationMailKind`) and what a
failure MEANS to a caller running a retry ladder (`MailFailureReport` — the
ladder is `retry.py`). The transport records them; it does not define them.

**No transport, no email.** There is no env-relay fallback here any more: the
relay is the transport's business (`mailintake` falls back to `RADD_SMTP_*`
itself). With nothing registered both loops record their pending rows as
undeliverable — stamped, the channel's "finished with this row" — and the inbox
is untouched. A mail plugin switched back on therefore does not empty a day of
backlog into everyone's mailbox.
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
    """What the transport should do with a delivery failure (RADD-997/1036).

    * `REPORT` — emit `mail.failed`. The send is over the moment it fails: a
      reply, an acknowledgement, a survey, an automation's email. The default,
      and right for everyone who is not running a ladder.
    * `SILENT` — a retry is coming, so the question the event answers ("did
      this person hear from us?") is not settled yet. The live incident wrote
      one event per recipient per five seconds into a stream every consumer
      reads.
    * `TERMINAL` — the last rung. Emitted, and marked given-up in the payload.

    Notify's because the ladder that makes a failure uninteresting is notify's
    (`retry.failure_report`). Three answers rather than two booleans, because
    "silent AND terminal" is nonsense and a second boolean would make it sayable.
    """

    REPORT = "report"
    SILENT = "silent"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class NotificationMail:
    """One composed message, handed to `MailTransport.send`.

    `item_id` set: the message is about ONE issue and threads on it (a reply
    lands back on the issue); `comment_id` names the comment it relays. Unset:
    a digest, or a notification about a non-item subject — nothing to thread on.
    `headers` are notify's own (`List-Unsubscribe`); a transport never lets them
    override the thread's.
    """

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
    """The registered transport, or None when email is unavailable.

    One transport per instance: the first provider registered answers. Read on
    every tick, never cached, so disabling the mail plugin takes effect on the
    next one.
    """
    return next(iter(sockets.providers(sockets.Socket.MAIL_TRANSPORT).values()), None)
