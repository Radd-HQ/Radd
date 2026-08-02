"""Pure raw-email → EmailPlan parsing (specs 47+62) — tested in
tests/test_connectors.py with fixture bytes. No I/O: user/item/project
resolution and writes happen in the poller."""

import re
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

from .types import BODY_MAX_CHARS

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


def _text_body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    try:
        return str(part.get_content())
    except Exception:  # undecodable part — treat as empty rather than crash intake
        return ""


def parse_email(raw: bytes) -> EmailPlan:
    message = message_from_bytes(raw, policy=policy.default)
    subject = str(message.get("Subject", "")).strip()
    sender_name, sender_email = parseaddr(str(message.get("From", "")))
    return EmailPlan(
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email.lower(),
        body=_text_body(message).strip()[:BODY_MAX_CHARS],
        item_key=extract_reply_key(subject),
        message_id=str(message.get("Message-ID", "")).strip(),
        project_key=extract_project_key(message),
    )
