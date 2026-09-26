"""Pure raw-email → EmailPlan parsing (specs 47+62). No I/O: resolution and
writes happen in `intake`."""

import re
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

from radd.mailtypes import MailAttachment

from .html_body import html_to_text
from .types import ATTACHMENTS_MAX_BYTES, AUTH_METHODS, BODY_MAX_CHARS, MAX_ATTACHMENTS

# An item key, same word-bounded grammar as the gitlab/forgejo connectors.
KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{0,9}-\d+)\b")
# The explicit reply-threading form: "[TD-123]" anywhere in the subject.
BRACKETED_KEY_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9]{0,9}-\d+)\]")
# A reply/forward subject prefix — only then does a bare key count as threading.
REPLY_PREFIX_RE = re.compile(r"^\s*(re|fwd?)\s*:", re.IGNORECASE)

# A project key (mirror of ProjectCreate.key) as a plus-address tag (spec 62):
# `support+td@…` routes intake to project TD.
PROJECT_KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,9}")
# Recipient headers inspected for the plus tag, in priority order.
PLUS_ADDRESS_HEADERS = ("To", "Cc", "Delivered-To", "X-Original-To")


@dataclass(frozen=True)
class EmailPlan:
    subject: str
    sender_name: str
    sender_email: str  # lower-cased address, "" when unparseable
    body: str  # text/plain body, truncated to BODY_MAX_CHARS
    item_key: str | None  # reply target key found in the subject, upper-cased
    message_id: str = ""  # inbound RFC Message-ID verbatim (threading, spec 62)
    project_key: str | None = None  # plus-address routing tag, upper-cased (spec 62)
    # --- RADD-951 wave ---
    #: Threading headers, verbatim. Parsed into candidates by `threading`.
    in_reply_to: str = ""
    references: str = ""
    #: RFC 3834's marker. Anything but "no" means a machine sent this (RADD-957).
    auto_submitted: str = ""
    #: The `From:` header unparsed (the loop guard compares its address).
    from_header: str = ""
    #: The body came from an HTML part (a lossy conversion).
    html_derived: bool = False
    attachments: tuple[MailAttachment, ...] = ()
    #: Attachment parts a per-message cap dropped (RADD-1035); `intake` notes them.
    attachments_dropped: int = 0
    #: Every address this was delivered to, lower-cased (RADD-958) — the only place
    #: `pipeline@` vs `help@` is visible when aliases share a mailbox.
    recipients: tuple[str, ...] = ()
    #: Every `Authentication-Results` header, verbatim (RADD-1032); which one to
    #: trust is the source's configured authserv-id.
    authentication_results: tuple[str, ...] = ()


def extract_reply_key(subject: str) -> str | None:
    """The item key a subject threads to: `[TD-123]` anywhere, or — for a
    `Re:`/`Fwd:` subject — the first bare key. None = not a reply."""
    match = BRACKETED_KEY_RE.search(subject)
    if match:
        return match.group(1).upper()
    if REPLY_PREFIX_RE.match(subject):
        match = KEY_RE.search(subject)
        if match:
            return match.group(1).upper()
    return None


def extract_project_key(message: EmailMessage) -> str | None:
    """The plus-address routing tag (spec 62): the first `anything+key@…` across the
    recipient headers wins; whether it names a REAL project is `intake`'s call."""
    for header in PLUS_ADDRESS_HEADERS:
        values = [str(value) for value in (message.get_all(header) or [])]
        for _, address in getaddresses(values):
            local, _, domain = address.partition("@")
            if not domain or "+" not in local:
                continue
            tag = local.rsplit("+", 1)[1]
            if PROJECT_KEY_RE.fullmatch(tag):
                return tag.upper()
    return None


def addresses(header_values: list[str]) -> list[str]:
    """The addresses in these header values, lower-cased — never the display form
    (a routing dry run must parse exactly as the live message is parsed)."""
    return [address.strip().lower() for _, address in getaddresses(header_values) if "@" in address]


def extract_recipients(message: EmailMessage) -> tuple[str, ...]:
    """Every delivery address on the message (the four recipient headers), deduped
    and lower-cased (RADD-958)."""
    found: dict[str, None] = {}
    for header in PLUS_ADDRESS_HEADERS:
        values = [str(value) for value in (message.get_all(header) or [])]
        for address in addresses(values):
            found.setdefault(address, None)
    return tuple(found)


def _body(message: EmailMessage) -> tuple[str, bool]:
    """(text, came_from_html): `text/plain`, else the HTML part (HTML-only mail is
    ordinary, RADD-956) STRIPPED to text rather than sanitised — no allow-list to
    get wrong."""
    part = message.get_body(preferencelist=("plain",))
    if part is not None:
        try:
            text = str(part.get_content()).strip()
        except Exception:  # undecodable part — fall through to HTML
            text = ""
        if text:
            return text, False
    part = message.get_body(preferencelist=("html",))
    if part is None:
        return "", False
    try:
        return html_to_text(str(part.get_content())), True
    except Exception:  # noqa: BLE001 — a broken part is input, not an error
        return "", False


def _attachments(message: EmailMessage) -> tuple[tuple[MailAttachment, ...], int]:
    """Every non-body part with content (inline images included), and how many a
    cap dropped (RADD-956/1035). Once a cap fires every LATER part is counted,
    not `break`-ed past, so the note names how many were lost; a part that fails
    to decode is skipped and not counted — it is not a cap."""
    found: list[MailAttachment] = []
    dropped = 0
    total = 0
    capped = False
    for part in message.iter_attachments():
        if capped:
            dropped += 1  # a later part, after some cap already fired
            continue
        if len(found) >= MAX_ATTACHMENTS:
            capped = True
            dropped += 1
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            continue
        if not payload:
            continue
        if total + len(payload) > ATTACHMENTS_MAX_BYTES:
            capped = True
            dropped += 1
            continue
        total += len(payload)
        name = part.get_filename() or f"attachment-{len(found) + 1}"
        found.append(
            MailAttachment(
                filename=str(name)[:255],
                content_type=part.get_content_type() or "application/octet-stream",
                data=payload,
            )
        )
    return tuple(found), dropped


# An `Authentication-Results` method verdict (`dkim=pass`); properties are ignored.
AUTH_METHOD_RE = re.compile(
    r"\b(" + "|".join(AUTH_METHODS) + r")\s*=\s*([A-Za-z]+)", re.IGNORECASE
)


def extract_authentication_results(message: EmailMessage) -> tuple[str, ...]:
    """Every `Authentication-Results` header value, verbatim (RADD-1032)."""
    return tuple(str(value) for value in (message.get_all("Authentication-Results") or []))


def parse_auth_results(
    headers: tuple[str, ...], authserv_id: str
) -> dict[str, str] | None:
    """The dkim/spf/dmarc verdicts stamped by `authserv_id` (RADD-1032) — the first
    token before `;`, matched case-insensitively; other authserv-ids are ignored.
    Reads the MX's stamp; no signature is validated here.

    None vs `{}` matters: None = that authserv said nothing (the ABSENT case the
    demotion note calls out), `{}` = it spoke but named no dkim/spf/dmarc.
    """
    wanted = authserv_id.strip().lower()
    if not wanted:
        return None
    for header in headers:
        authserv, _, rest = header.partition(";")
        # The authserv-id may carry a version: `mx.example.com 1;` — take the
        # first whitespace-separated token.
        serv = authserv.strip().split()[0].lower() if authserv.strip() else ""
        if serv != wanted:
            continue
        verdicts: dict[str, str] = {}
        for method, result in AUTH_METHOD_RE.findall(rest):
            verdicts.setdefault(method.lower(), result.lower())
        return verdicts
    return None


def parse_email(raw: bytes) -> EmailPlan:
    message = message_from_bytes(raw, policy=policy.default)
    subject = str(message.get("Subject", "")).strip()
    from_header = str(message.get("From", ""))
    sender_name, sender_email = parseaddr(from_header)
    body, html_derived = _body(message)
    attachments, attachments_dropped = _attachments(message)
    return EmailPlan(
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email.lower(),
        body=body.strip()[:BODY_MAX_CHARS],
        item_key=extract_reply_key(subject),
        message_id=str(message.get("Message-ID", "")).strip(),
        project_key=extract_project_key(message),
        in_reply_to=str(message.get("In-Reply-To", "")).strip(),
        references=str(message.get("References", "")).strip(),
        auto_submitted=str(message.get("Auto-Submitted", "")).strip(),
        from_header=from_header,
        html_derived=html_derived,
        attachments=attachments,
        attachments_dropped=attachments_dropped,
        recipients=extract_recipients(message),
        authentication_results=extract_authentication_results(message),
    )
