"""Shared synchronous SMTP send helper (spec 62).

One place composes and ships an outbound plain-text email over the `smtp_*`
settings; callers wrap it in `asyncio.to_thread` (stdlib smtplib blocks).
The "is SMTP configured at all" guard stays at the CALLERS — an empty
`smtp_host` means their whole feature is disabled, which each caller decides
for itself (notify skips the digest loop, mailintake skips acks/replies).

Consumers: notify's digest emailer, mailintake acks + comment replies (spec 62),
CSAT (spec 65) and the automation send_email action (spec 66).
"""

import smtplib
from collections.abc import Mapping
from email.message import EmailMessage
from email.utils import make_msgid

from radd.config import settings

# Connect + send bound per message — an unreachable relay must not wedge a worker.
SMTP_TIMEOUT_SECONDS = 15.0


def send_message(
    to_address: str,
    subject: str,
    body: str,
    *,
    to_name: str = "",
    headers: Mapping[str, str] | None = None,
) -> str:
    """Send one plain-text email; return the `Message-ID` that was ACTUALLY SENT.

    The return value is not a convenience (RADD-955). Threading depends on
    storing the id the provider used, and the two can differ: SMTP lets a client
    set its own, so passing one through `headers` and storing that is right by
    luck, but the Gmail API replaces it. Storing an intended value the provider
    did not use means every reply arrives unthreaded and opens a duplicate
    issue — days later, at a customer, with no error raised anywhere.

    So the id is read back off the composed message rather than assumed, and one
    is generated when the caller supplied none: a message with no `Message-ID` is
    a thread that can never be replied into.

    `headers` adds extra headers verbatim (In-Reply-To/References). Raises on
    delivery failure — callers choose between retry (notify digests) and
    log-and-drop.
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = f"{to_name} <{to_address}>" if to_name else to_address
    for key, value in (headers or {}).items():
        if value:
            message[key] = value
    if not message.get("Message-ID"):
        message["Message-ID"] = make_msgid()
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
    # Read BACK off the message, not from the local variable — this is the value
    # that went on the wire.
    return str(message["Message-ID"])
