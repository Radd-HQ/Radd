"""Outbound transports. `sender_for` is the ONE kind→implementation map
(RADD-969), shared by the transport and the settings test-send."""

from ..providers import MailSender as MailSenderProtocol
from ..types import SMTP_SENDER_KINDS
from .smtp_sender import SmtpSender

__all__ = ["SmtpSender", "sender_for"]


def sender_for(row) -> MailSenderProtocol | None:
    """The transport for a `mail_senders` row, or None; the presets are SMTP too."""
    if row.kind in SMTP_SENDER_KINDS:
        return SmtpSender(row)
    return None
