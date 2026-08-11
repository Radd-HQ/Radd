"""Pure raw-email → EmailPlan parsing (specs 47+62) — tested in
tests/test_connectors.py with fixture bytes. No I/O: user/item/project
resolution and writes happen in the poller."""

import re
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

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
class MailAttachment:
    """One decoded attachment part (RADD-956) — handed to `attachments.save_blob`."""

    filename: str
    content_type: str
    content: bytes


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
    #: The `From:` header unparsed — the loop guard compares addresses, and the
    #: item body quotes the display form.
    from_header: str = ""
    #: True when the body came from an HTML part rather than text/plain. Worth
    #: knowing when a body reads oddly: the converter is lossy by design.
    html_derived: bool = False
    attachments: tuple[MailAttachment, ...] = ()
    #: How many attachment parts a per-message cap dropped (RADD-1035). Non-zero
    #: earns the sender a receipt: `intake` leaves a note on the item naming the
    #: count, because a screenshot that silently vanished is a support failure.
    attachments_dropped: int = 0
    #: Every address this was delivered to, lower-cased (RADD-958). Aliases share
    #: a mailbox on most hosts, so `pipeline@` vs `help@` is ONLY visible here —
    #: the IMAP connection cannot tell them apart.
    recipients: tuple[str, ...] = ()
    #: Every `Authentication-Results` header, verbatim (RADD-1032). A message
    #: crosses several hosts and each may stamp its own, so this is a tuple; which
    #: one to TRUST is the source's configured authserv-id, read at ingest. Radd
    #: is reading its MX's verdict here, not doing crypto — the header is the
    #: mechanism, `parse_auth_results` the conservative reader.
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
    """The plus-address routing tag (spec 62): the first recipient address of the
    form `anything+key@…` across To/Cc/Delivered-To/X-Original-To wins. The tag
    must scan as a project key; whether it names a REAL project is the poller's
    call (unknown keys fall back to RADD_MAIL_PROJECT_KEY)."""
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


def extract_recipients(message: EmailMessage) -> tuple[str, ...]:
    """Every delivery address on the message, deduped and lower-cased (RADD-958).

    The same four headers `extract_project_key` walks — that function reads them
    for a plus-tag and throws the addresses away, which is why alias routing had
    nothing to match on.

    This is the ONLY place `pipeline@` and `help@` are distinguishable: on most
    hosts an alias delivers into a shared mailbox, so the IMAP connection sees
    one inbox and the alias survives only in the headers.
    """
    found: dict[str, None] = {}
    for header in PLUS_ADDRESS_HEADERS:
        values = [str(value) for value in (message.get_all(header) or [])]
        for _, address in getaddresses(values):
            if "@" in address:
                found.setdefault(address.strip().lower(), None)
    return tuple(found)


def _body(message: EmailMessage) -> tuple[str, bool]:
    """(text, came_from_html). Prefer `text/plain`; fall back to HTML converted
    to text (RADD-956).

    An HTML-only message is completely ordinary — Outlook, phones and every
    marketing system send them — and taking plain-and-stopping turned each one
    into a blank ticket. The HTML is STRIPPED to text rather than sanitised:
    nothing survives as markup, so there is no allow-list to get wrong.
    """
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
    """Every non-body part with content, and how many a cap dropped (RADD-956/1035).

    `iter_attachments` covers the inline-image case too — a screenshot pasted
    into Outlook arrives as a related part with a Content-ID, and a ticket
    without it is missing the whole point of the message. Parts that fail to
    decode are dropped individually: one bad part must not cost the message.

    The second return value is the count dropped by a CAP — the count or the
    size limit. Once a cap is hit every later part is counted and skipped rather
    than the loop `break`ing, so `intake` can leave the sender a receipt naming
    how many were lost. A decode failure or an empty part is NOT counted: that
    is a property of the one part, not a cap the sender can work around by
    resending.
    """
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
                content=payload,
            )
        )
    return tuple(found), dropped


# An `Authentication-Results` method verdict: `dkim=pass`, `spf = fail`, etc.
# The result token is the first word after `=`; properties (`header.d=…`) follow
# and are ignored — the verdict is all a trusted authserv-id stamp needs to say.
AUTH_METHOD_RE = re.compile(
    r"\b(" + "|".join(AUTH_METHODS) + r")\s*=\s*([A-Za-z]+)", re.IGNORECASE
)


def extract_authentication_results(message: EmailMessage) -> tuple[str, ...]:
    """Every `Authentication-Results` header value, verbatim (RADD-1032).

    A tuple because a message crosses several hosts and each may add its own;
    only the one whose authserv-id the source TRUSTS is read, at ingest.
    """
    return tuple(str(value) for value in (message.get_all("Authentication-Results") or []))


def parse_auth_results(
    headers: tuple[str, ...], authserv_id: str
) -> dict[str, str] | None:
    """The dkim/spf/dmarc verdicts stamped by `authserv_id`, or None if it stamped none.

    Conservative by construction (RADD-1032): find the `Authentication-Results`
    block whose authserv-id — the first token, before the first `;` and any
    version number — matches (case-insensitively), then read each
    `method=result` token for the methods we care about. A block we cannot make
    sense of yields `{}` (present but empty), and a header from an authserv-id we
    do not trust is ignored entirely. Nothing here validates a signature; it
    reads the MX's stamp, which is the whole point — the crypto happened upstream.

    None vs `{}` matters to the caller: None is "that authserv said nothing about
    this message" (absent), `{}` is "it spoke but named no dkim/spf/dmarc". Both
    are treated as unverified, but only the first is the ABSENT case the demotion
    note calls out.
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
