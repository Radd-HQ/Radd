"""Outbound transports (RADD-955/958). `smtp` is the only wire so far; a Gmail
API adapter registers here and changes nothing above it.

`sender_for` is the ONE place a kind becomes an implementation (RADD-969).
There used to be two — the outbound consumer's own dispatch (RADD-968 moved it
into `transport._sender`) and the settings test-send — which is how the test
button came to answer "no implementation for kind 'google'" for a sender the
transport was happily using. A kind added in one place and not the other is a
silent half-feature, so both call this.
"""

from ..providers import MailSender as MailSenderProtocol
from ..types import SMTP_SENDER_KINDS
from .smtp_sender import SmtpSender

__all__ = ["SmtpSender", "sender_for"]


def sender_for(row) -> MailSenderProtocol | None:
    """The transport for a `mail_senders` row, or None when nothing serves it.

    Gmail and Outlook are SMTP with the connection already answered (their
    preset supplies host/port/TLS) — the same class, not a subclass.
    """
    if row.kind in SMTP_SENDER_KINDS:
        return SmtpSender(row)
    return None
