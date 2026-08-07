"""SMTP `MailSender` (RADD-955).

Thin on purpose: it wraps `radd.smtp.send_message`, which every other mail
consumer already uses (notify digests, CSAT, the automation send_email action),
so there is one place that speaks SMTP.

The only thing it adds is the contract that matters — `send` returns the
Message-ID that actually went out, read back off the composed message rather
than assumed from what was passed in.
"""

from __future__ import annotations

import asyncio

from radd import smtp

from ..providers import OutboundMessage


class SmtpSender:
    """Sends over one `mail_senders` row (RADD-958).

    The row is the whole configuration — host, credentials, identity — so an
    instance can hold several and outbound picks by `is_default` rather than by
    whatever the environment last said.
    """

    kind = "smtp"

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
            config=smtp.SmtpConfig(
                host=self._row.host,
                port=self._row.port,
                username=self._row.username,
                password=self._row.secret,
                starttls=self._row.starttls,
                from_address=self._row.from_address,
            ),
        )
