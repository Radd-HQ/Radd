"""Synchronous SMTP transport; callers wrap it in `asyncio.to_thread` (smtplib blocks).
What a message SAYS is composed in `radd/mailrender.py`; the relay is the caller's."""

import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid

from radd.mailtypes import MailAttachment

# Connect + send bound per message — an unreachable relay must not wedge a worker.
SMTP_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class SmtpConfig:
    """One relay's settings, read by mailintake from a `mail_senders` row (RADD-958)."""

    host: str
    port: int
    username: str
    password: str
    starttls: bool
    from_address: str


def send_message(
    to_address: str,
    subject: str,
    body: str,
    *,
    to_name: str = "",
    headers: Mapping[str, str] | None = None,
    config: SmtpConfig,
    html_body: str | None = None,
    attachments: tuple[MailAttachment, ...] = (),
) -> str:
    """Send one email; return the `Message-ID` that ACTUALLY went out.

    `body` is the plain-text part and is never optional (html-only reads as empty to text
    clients and spam filters); `html_body` makes it multipart/alternative. The id is read back
    off the composed message, and generated when `headers` carry none: threading needs the id
    the provider used — the Gmail API replaces a client's own (RADD-955) — and a message
    without one can never be replied into. Raises on delivery failure."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = f"{to_name} <{to_address}>" if to_name else to_address
    for key, value in (headers or {}).items():
        if value:
            message[key] = value
    if not message.get("Message-ID"):
        message["Message-ID"] = make_msgid()
    message.set_content(body)
    if html_body:
        # After set_content, so the text part stays FIRST — `multipart/alternative`
        # is ordered worst-to-best and a client shows the last part it can render.
        message.add_alternative(html_body, subtype="html")
    for attachment in attachments:
        maintype, subtype = attachment.content_type.split("/", 1)
        message.add_attachment(
            attachment.data, maintype=maintype, subtype=subtype, filename=attachment.filename
        )
    with smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        if config.starttls:
            smtp.starttls()
        if config.username:
            smtp.login(config.username, config.password)
        smtp.send_message(message)
    # Read BACK off the message, not from the local variable — this is the value
    # that went on the wire.
    return str(message["Message-ID"])
