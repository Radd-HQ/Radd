"""Shared synchronous SMTP send helper (spec 62).

One place ships an outbound email over the `smtp_*` settings; callers wrap it in
`asyncio.to_thread` (stdlib smtplib blocks). What the message SAYS is composed in
`radd/mailrender.py` (RADD-967) — this file is transport.
The "is SMTP configured at all" guard stays at the CALLERS — an empty
`smtp_host` means their whole feature is disabled, which each caller decides
for itself (notify skips the digest loop, mailintake skips acks/replies).

Consumers: notify's digest emailer, mailintake acks + comment replies (spec 62),
CSAT (spec 65) and the automation send_email action (spec 66).
"""

import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid

from radd.config import settings
from radd.mailtypes import MailAttachment

# Connect + send bound per message — an unreachable relay must not wedge a worker.
SMTP_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class SmtpConfig:
    """One relay's settings. Passed explicitly by `mailintake`, which reads them
    from a `mail_senders` ROW (RADD-958); omitted by every other caller, which
    still uses the `smtp_*` environment settings.

    Both paths exist on purpose. Mail-as-a-channel is configurable in the UI;
    notification digests, CSAT and the automation send_email action are instance
    plumbing that has never needed a second relay.
    """

    host: str
    port: int
    username: str
    password: str
    starttls: bool
    from_address: str


def _env_config() -> SmtpConfig:
    return SmtpConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        starttls=settings.smtp_starttls,
        from_address=settings.smtp_from_address,
    )


def send_message(
    to_address: str,
    subject: str,
    body: str,
    *,
    to_name: str = "",
    headers: Mapping[str, str] | None = None,
    config: SmtpConfig | None = None,
    html_body: str | None = None,
    attachments: tuple[MailAttachment, ...] = (),
) -> str:
    """Send one email; return the `Message-ID` that was ACTUALLY SENT.

    `body` is the plain-text part and is never optional: an html-only message is
    the one a text client, a screen reader and every spam filter reads as empty.
    Passing `html_body` makes the message `multipart/alternative` — same content,
    two renderings, the client picks (RADD-967).

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
    cfg = config or _env_config()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg.from_address
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
    with smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        if cfg.starttls:
            smtp.starttls()
        if cfg.username:
            smtp.login(cfg.username, cfg.password)
        smtp.send_message(message)
    # Read BACK off the message, not from the local variable — this is the value
    # that went on the wire.
    return str(message["Message-ID"])
