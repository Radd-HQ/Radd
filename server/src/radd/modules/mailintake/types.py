"""Wire constants for the email-to-issue intake (spec 47) and the requester
feedback loop — contacts, acks, outbound replies (spec 62)."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class MailEntity(StrEnum):
    MAIL = "mail_intake"
    CONTACT = "mail_contact"
    MESSAGE = "mail_message"
    SOURCE = "mail_source"
    SENDER = "mail_sender"


class MailEvent(StrEnum):
    """What the mail channel itself did (RADD-960).

    Before these, `mailintake` emitted nothing of its own — automations could see
    the ITEM intake created and the COMMENT it appended, but never that the cause
    was email. A rule could not tell a customer's reply from an agent typing in
    the UI, which is the distinction a service desk runs on.

    They need no edit to `automations`: `catalog.TRIGGERS` derives live from the
    kernel event-type registry, so declaring them on the manifest is enough.
    """

    RECEIVED = "mail.received"
    SENT = "mail.sent"
    DROPPED = "mail.dropped"
    FAILED = "mail.failed"


class MailSourceKind(StrEnum):
    """How mail reaches Radd. A kind is a registered implementation resolved by
    ROW, so a Gmail adapter is a class plus a row (RADD-958).

    GOOGLE and OUTLOOK are **presets, not transports** (RADD-969): both are
    polled over IMAP by the very same code, and the kind exists only so the row
    can leave the connection blank and inherit it from `KIND_DEFAULTS`. That is
    the spec-110 rule — a kind supplies defaults, never a second engine.
    """

    WEBHOOK = "webhook"   # HTTPS push (a Worker today, Gmail push later)
    IMAP = "imap"         # a polled mailbox — what radd-hq.com runs (RADD-959)
    GOOGLE = "google"     # Gmail / Google Workspace, over IMAP (RADD-969)
    OUTLOOK = "outlook"   # Outlook.com / Microsoft 365, over IMAP (RADD-969)


class MailSenderKind(StrEnum):
    """Where mail goes out. GOOGLE and OUTLOOK are SMTP with the host, port and
    TLS mode already answered — see `MailSourceKind` (RADD-969)."""

    SMTP = "smtp"
    GOOGLE = "google"
    OUTLOOK = "outlook"


#: Source kinds the IMAP poller walks. A preset kind is polled exactly like a
#: hand-configured mailbox — the only difference is where its host comes from.
POLLED_SOURCE_KINDS: tuple[MailSourceKind, ...] = (
    MailSourceKind.IMAP,
    MailSourceKind.GOOGLE,
    MailSourceKind.OUTLOOK,
)

#: Sender kinds `senders.sender_for` hands to `SmtpSender`. Gmail and Outlook
#: both speak submission SMTP; a Gmail API adapter would be a NEW kind, not a
#: second meaning for this one.
SMTP_SENDER_KINDS: tuple[MailSenderKind, ...] = (
    MailSenderKind.SMTP,
    MailSenderKind.GOOGLE,
    MailSenderKind.OUTLOOK,
)

# Column defaults, named because three files state them: the model, the write
# schema and the preset table.
DEFAULT_IMAP_PORT = 993
DEFAULT_SMTP_PORT = 587
DEFAULT_IMAP_FOLDER = "INBOX"

#: Where an operator creates the app password each preset needs. Both providers
#: refuse an account password over SMTP/IMAP, so a form that does not say so
#: produces an authentication failure nobody can explain.
GOOGLE_APP_PASSWORD_URL = "https://support.google.com/accounts/answer/185833"
OUTLOOK_APP_PASSWORD_URL = (
    "https://support.microsoft.com/en-us/account-billing/"
    "5896ed9b-4263-e681-128a-a6f2979a7944"
)


@dataclass(frozen=True)
class MailKindPreset:
    """What a kind answers on the operator's behalf (RADD-969).

    Copied from spec 110's `KIND_DEFAULTS` including the part that matters:
    **the row stores BLANK where the preset answers**, and resolution happens at
    READ time (`resolve.py`). Baking `smtp.gmail.com` into the row at save time
    would freeze it — upgrading the preset would then leave every existing row
    pointing at the old value, which is exactly what "a kind supplies defaults"
    is supposed to prevent.

    One preset serves both halves: a Gmail mailbox and a Gmail relay are one
    provider answering two questions, so the source and sender enums share the
    kind's VALUE and this table is keyed by it.
    """

    #: Short label — the name a new row is auto-named after.
    name: str
    #: One line for the picker: what this kind actually is.
    summary: str = ""
    smtp_host: str = ""
    smtp_port: int = DEFAULT_SMTP_PORT
    smtp_starttls: bool = True
    imap_host: str = ""
    imap_port: int = DEFAULT_IMAP_PORT
    #: Shown in the form when the preset carries an operational precondition.
    guidance: str = ""
    help_url: str = ""

    @property
    def answers_smtp(self) -> bool:
        """True when the sender form should hide host/port/TLS entirely."""
        return bool(self.smtp_host)

    @property
    def answers_imap(self) -> bool:
        return bool(self.imap_host)


#: No preset — a kind the operator configures in full.
EMPTY_PRESET = MailKindPreset(name="")

_GOOGLE_GUIDANCE = (
    "Google rejects an account password over SMTP and IMAP. This mailbox needs "
    "2-Step Verification switched on and a 16-character app password, which is "
    "what you paste below."
)
_OUTLOOK_GUIDANCE = (
    "Microsoft rejects an account password over SMTP and IMAP on accounts with "
    "modern authentication. Create an app password and paste it below. "
    "Microsoft 365 tenants must also have IMAP/SMTP AUTH enabled for the mailbox."
)

#: Per-kind defaults, keyed by the kind's VALUE — which `MailSourceKind` and
#: `MailSenderKind` deliberately share for the preset kinds (`StrEnum` members
#: hash as their strings, so either enum indexes this table).
KIND_DEFAULTS: dict[str, MailKindPreset] = {
    MailSourceKind.WEBHOOK: MailKindPreset(
        name="Webhook",
        summary="Something pushes messages to Radd over HTTPS",
    ),
    MailSourceKind.IMAP: MailKindPreset(
        name="IMAP mailbox",
        summary="Any IMAP server — you supply the host",
    ),
    MailSenderKind.SMTP: MailKindPreset(
        name="SMTP relay",
        summary="Any SMTP relay — you supply the host",
    ),
    MailSourceKind.GOOGLE: MailKindPreset(  # == MailSenderKind.GOOGLE
        name="Gmail",
        summary="Gmail or Google Workspace",
        smtp_host="smtp.gmail.com",
        imap_host="imap.gmail.com",
        guidance=_GOOGLE_GUIDANCE,
        help_url=GOOGLE_APP_PASSWORD_URL,
    ),
    MailSourceKind.OUTLOOK: MailKindPreset(  # == MailSenderKind.OUTLOOK
        name="Outlook",
        summary="Outlook.com, Hotmail or Microsoft 365",
        smtp_host="smtp-mail.outlook.com",
        imap_host="outlook.office365.com",
        guidance=_OUTLOOK_GUIDANCE,
        help_url=OUTLOOK_APP_PASSWORD_URL,
    ),
}


class MailRuleType(StrEnum):
    """Builtin routing-rule kinds (RADD-958/961).

    Cheap first by convention: the three deterministic kinds cost nothing, `llm`
    costs an inference, so the seeded order puts it last and only mail no other
    rule claimed pays for it.
    """

    RECIPIENT = "recipient"      # the alias it was delivered to — help@ vs pipeline@
    SENDER = "sender"            # a sender address, or a whole @domain
    SUBJECT = "subject"          # a case-insensitive substring of the Subject
    LLM = "llm"                  # classify the CONTENT into a project (RADD-961)


class MailRecipientKind(StrEnum):
    """Why an address is on an outbound reply (RADD-967).

    It decides one thing — the footer's wording — and that is worth an enum
    because the two are not interchangeable: a colleague is watching an issue
    they can open, and the requester is a customer who has no account and whose
    only interface is replying. A single "you are receiving this" line would be
    wrong for one of them whichever way it was written.
    """

    WATCHER = "watcher"
    REQUESTER = "requester"


class MailDirection(StrEnum):
    """Which way a `mail_messages` row went. Threading only ever resolves
    against OUTBOUND ids (what a reply's In-Reply-To can name); dedup only ever
    consults INBOUND ones."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


# --- the RADD-951 wave ---

#: Cloudflare Email Routing's own ceiling — matching it means Radd rejects
#: exactly what the provider would have, rather than inventing a second limit.
MAX_BODY_BYTES = 25 * 1024 * 1024

#: Attachment caps (RADD-956). Per message, not per part: the failure to prevent
#: is one message becoming a hundred rows or a hundred megabytes.
MAX_ATTACHMENTS = 20
ATTACHMENTS_MAX_BYTES = 20 * 1024 * 1024

#: How far back a repeated inbound Message-ID still counts as a duplicate.
#: Every push provider is at-least-once and Cloudflare retries on timeout, so
#: this is the difference between one ticket and two. Seven days because that is
#: longer than any provider's retry schedule and short enough that the table
#: does not become the archive of every message ever received.
DEDUP_WINDOW = timedelta(days=7)


# Label applied to every mail-created item (resolved through the labels seam).
EMAIL_LABEL = "email"

# Description = the text/plain body truncated to this many chars (spec 47).
BODY_MAX_CHARS = 10_000

# Item titles are capped at 500 chars (items.schemas.ItemCreate).
TITLE_MAX_CHARS = 500

# Title fallback for an empty Subject header.
NO_SUBJECT_TITLE = "(no subject)"

# Body fallback so comment/description bodies are never empty.
EMPTY_BODY_PLACEHOLDER = "(empty message)"

# The IMAP flag used as the intake cursor (spec 47 — no state table).
SEEN_FLAG = r"(\Seen)"

# Reply comments are authored by the SYSTEM actor; the real sender is noted in the body.
REPLY_COMMENT_TEMPLATE = "Email reply from {sender}:\n\n{body}"

# Appended to the description when the sender matches no user (spec 47).
SENDER_NOTE_TEMPLATE = "{body}\n\n---\nReceived by email from {sender}"

# --- requester loop (spec 62) ---

# The outbound consumer's cursor name in the events stream.
OUTBOUND_CONSUMER_NAME = "mailintake.outbound"

# Events read per outbound poll iteration (mirrors googlechat's batch).
OUTBOUND_BATCH = 200

# Acknowledgment sent when intake/public-form submission creates an item with a
# contact. The bracketed key in the subject is what threads the requester's
# replies back onto the item (parsing.extract_reply_key) — which is why the
# SUBJECTS live here as wire constants while the bodies live in
# `radd.mailrender` with every other rendering decision (RADD-967).
ACK_SUBJECT_TEMPLATE = "[{key}] {title}"

# Outbound reply to the contact when an agent leaves a PUBLIC comment.
REPLY_SUBJECT_TEMPLATE = "Re: [{key}] {title}"

# Why each recipient is being written to — the footer of an outbound reply.
REPLY_REASON_TEMPLATES = {
    MailRecipientKind.WATCHER: "You are watching {key} — reply to this email to comment.",
    MailRecipientKind.REQUESTER: (
        "You are receiving this because you contacted us about {key} — "
        "reply to this email to add to the ticket."
    ),
}
