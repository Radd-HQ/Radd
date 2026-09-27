"""SMTP `MailSender` (RADD-955): a thin wrapper over `radd.smtp.send_message`
whose `send` returns the Message-ID that actually went out."""

from __future__ import annotations

import asyncio

from radd import secretbox, smtp

from .. import resolve
from ..providers import OutboundMessage
from ..types import MailSenderKind


class SmtpSender:
    """Sends over one `mail_senders` row (RADD-958), connection details RESOLVED
    against the kind's preset (RADD-969)."""

    kind = MailSenderKind.SMTP.value

    def __init__(self, row) -> None:
        self._row = row

    async def send(self, message: OutboundMessage) -> str:
        # stdlib smtplib blocks; every caller in this codebase threads it.
        return await asyncio.to_thread(
            smtp.send_message,
            message.to_address,
            message.subject,
            message.body,
            to_name=message.to_name,
            headers=dict(message.headers),
            html_body=message.html_body or None,
            attachments=message.attachments,
            config=smtp.SmtpConfig(
                host=resolve.sender_host(self._row),
                port=resolve.sender_port(self._row),
                username=resolve.sender_username(self._row),
                # The one place an SMTP password is decrypted (RADD-1446); the env
                # relay's `_EnvSender` carries plaintext, which passes through.
                password=secretbox.decrypt(self._row.secret),
                starttls=resolve.sender_starttls(self._row),
                from_address=self._row.from_address,
            ),
        )
