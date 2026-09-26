"""Wire constants for the email-to-issue intake (spec 47) and the requester
feedback loop — contacts, acks, outbound replies (spec 62)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class MailEntity(StrEnum):
    MAIL = "mail_intake"
    CONTACT = "mail_contact"
    MESSAGE = "mail_message"
    SOURCE = "mail_source"
    SENDER = "mail_sender"
    RULE = "mail_rule"


class MailEvent(StrEnum):
    """What the mail channel itself did (RADD-960) — so a rule can tell a
    customer's reply from an agent typing."""

    RECEIVED = "mail.received"
    SENT = "mail.sent"
    DROPPED = "mail.dropped"
    FAILED = "mail.failed"
    # Spec 123: mail configuration (sources, senders, routing rules), audited
    # with a diff; a password appears only as "changed". Not triggers.
    SOURCE_CREATED = "mail_source.created"
    SOURCE_UPDATED = "mail_source.updated"
    SOURCE_DELETED = "mail_source.deleted"
    SENDER_CREATED = "mail_sender.created"
    SENDER_UPDATED = "mail_sender.updated"
    SENDER_DELETED = "mail_sender.deleted"
    RULE_CREATED = "mail_rule.created"
    RULE_UPDATED = "mail_rule.updated"
    RULE_DELETED = "mail_rule.deleted"


class SentMailKind(StrEnum):
    """WHAT a sent mail was, carried as `kind` on `mail.sent`/`mail.failed`
    (RADD-1318); required of every caller, so "we replied" never matches the
    digest. Notify names its own two (`NotificationMailKind`)."""

    REPLY = "reply"  # a public comment relayed to the requester
    SURVEY = "survey"  # a CSAT survey
    AUTOMATION = "automation"  # an automation's Send email
    RECEIPT = "receipt"  # the desk's receipt for a new email ticket (RADD-1368)
    RESOLUTION = "resolution"  # the desk's resolution notice (RADD-1368)


#: RADD-1385: this plugin's provider name on the kernel MAIL_TRANSPORT socket.
MAIL_TRANSPORT_NAME = "mailintake"


class MailSourceKind(StrEnum):
    """How mail reaches Radd (RADD-958). GOOGLE and OUTLOOK are PRESETS, not
    transports (RADD-969): polled over IMAP by the same code, the kind only lets
    the row inherit its connection from `KIND_DEFAULTS`."""

    WEBHOOK = "webhook"   # HTTPS push (a Worker today, Gmail push later)
    IMAP = "imap"         # a polled mailbox — what radd-hq.com runs (RADD-959)
    GOOGLE = "google"     # Gmail / Google Workspace, over IMAP (RADD-969)
    OUTLOOK = "outlook"   # Outlook.com / Microsoft 365, over IMAP (RADD-969)


class MailSenderKind(StrEnum):
    """Where mail goes out; GOOGLE and OUTLOOK are SMTP presets (RADD-969)."""

    SMTP = "smtp"
    GOOGLE = "google"
    OUTLOOK = "outlook"


#: Source kinds the IMAP poller walks (a preset is polled like any mailbox).
POLLED_SOURCE_KINDS: tuple[MailSourceKind, ...] = (
    MailSourceKind.IMAP,
    MailSourceKind.GOOGLE,
    MailSourceKind.OUTLOOK,
)

#: Sender kinds `senders.sender_for` hands to `SmtpSender`; a Gmail API adapter
#: would be a NEW kind.
SMTP_SENDER_KINDS: tuple[MailSenderKind, ...] = (
    MailSenderKind.SMTP,
    MailSenderKind.GOOGLE,
    MailSenderKind.OUTLOOK,
)

# Column defaults shared by the model, the write schema and the preset table.
DEFAULT_IMAP_PORT = 993
DEFAULT_SMTP_PORT = 587
DEFAULT_IMAP_FOLDER = "INBOX"

#: Where to create the app password each preset needs — both providers refuse an
#: account password over SMTP/IMAP.
GOOGLE_APP_PASSWORD_URL = "https://support.google.com/accounts/answer/185833"
OUTLOOK_APP_PASSWORD_URL = (
    "https://support.microsoft.com/en-us/account-billing/"
    "5896ed9b-4263-e681-128a-a6f2979a7944"
)


@dataclass(frozen=True)
class MailKindPreset:
    """What a kind answers for the operator (RADD-969). The row stores BLANK where
    the preset answers (`resolve.py`). One preset serves both halves; the table is
    keyed by the kind's VALUE."""

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

#: Per-kind defaults, keyed by the kind's VALUE, which both enums share for the
#: presets (`StrEnum` members hash as their strings).
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


class EmailRecipient(StrEnum):
    """Role values the Send email node's `to` may name (spec 66) — anything else
    is a literal address. Resolved on the run's ONE target item: reporter/assignee
    when `mailable_user`, contact = the primary mail contact; none → skip-log."""

    REPORTER = "reporter"
    ASSIGNEE = "assignee"
    CONTACT = "contact"


class MailRuleType(StrEnum):
    """Builtin routing-rule kinds (RADD-958/961); `llm` costs an inference, so it
    is seeded last."""

    RECIPIENT = "recipient"      # the alias it was delivered to — help@ vs pipeline@
    SENDER = "sender"            # a sender address, or a whole @domain
    SUBJECT = "subject"          # a case-insensitive substring of the Subject
    LLM = "llm"                  # classify the CONTENT into a project (RADD-961)


class MailRuleStatus(StrEnum):
    """What ONE rule did on ONE message — the dry run's vocabulary (RADD-989/994).
    ERRORED is distinct from DECLINED so a crashed rule never reads as an
    inapplicable one; DISABLED and NOT_REACHED exist so an absent row means only
    "no such rule"."""

    MATCHED = "matched"
    DECLINED = "declined"
    ERRORED = "errored"
    DISABLED = "disabled"        # switched off — the walk skipped it (RADD-994)
    NOT_REACHED = "not_reached"  # an earlier rule matched and stopped the chain


#: The extra choice every llm rule offers (RADD-989), so declining is a verdict
#: rather than a forced wrong category. Appended at ask time, never stored.
NO_MATCH_ANSWER = "None of these"


class MailDirection(StrEnum):
    """Which way a `mail_messages` row went: threading resolves against OUTBOUND
    ids, dedup consults INBOUND ones."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


# --- the RADD-951 wave ---

#: Cloudflare Email Routing's own ceiling, rather than a second limit.
MAX_BODY_BYTES = 25 * 1024 * 1024

#: Attachment caps per MESSAGE, not per part (RADD-956).
MAX_ATTACHMENTS = 20
ATTACHMENTS_MAX_BYTES = 20 * 1024 * 1024

#: The SYSTEM note `intake` leaves when a cap dropped later parts (RADD-1035) —
#: a silent drop is what the cap must not be.
ATTACHMENTS_DROPPED_NOTE = (
    "{count} attachment(s) on the inbound email were not stored — the message hit "
    "Radd's per-message attachment cap ({max_count} files / {max_mb} MB). Ask the "
    "sender to resend the rest as separate, smaller emails if they are needed."
)

#: How far back a repeated inbound Message-ID still counts as a duplicate: push
#: providers are at-least-once; longer than any provider's retry schedule.
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

# --- sender authentication (RADD-1032) ---

#: RFC 8601 result tokens. Only `pass` proves a method; `none`/`neutral` prove
#: nothing and are treated as unverified too.
AUTH_PASS_RESULT = "pass"
AUTH_FAIL_RESULTS = frozenset({"fail", "softfail", "hardfail", "permerror", "temperror"})
#: The three methods a trusted authserv-id verdict is read for. Radd is trusting
#: its MX's stamp, not verifying crypto itself, so this is the whole vocabulary.
AUTH_METHODS = ("dkim", "spf", "dmarc")

#: A message that FAILS or OMITS a trusted authserv-id verdict is recorded as
#: received but attributed to nobody: a forged staff `From:` cannot speak as that
#: person, stop the SLA clock, or be relayed to the requester.
UNVERIFIED_SENDER_LINE = (
    "Unverified sender — this message failed sender authentication ({detail}) at "
    "the mail gateway, so its From address may be forged. Recorded as received; "
    "not attributed to any account."
)
#: A demoted reply keeps the SYSTEM prefix AND leads with the warning.
UNVERIFIED_REPLY_COMMENT_TEMPLATE = "{note}\n\nEmail reply from {sender}:\n\n{body}"
#: A demoted new issue's description: the body, then the warning and the claimed sender.
UNVERIFIED_SENDER_NOTE_TEMPLATE = "{body}\n\n---\n{note}\nReceived by email from {sender}"

# --- raw-message retention (RADD-1033) ---

#: Raw bytes of an ingested message are kept so an over-eager quote strip or a
#: lost attachment is recoverable. `0` = do not retain (some desks must not keep
#: customer mail at rest).
MAIL_RAW_RETENTION_DAYS = 30

#: The raw message is stored as one loose blob through the spec-102 seam.
RAW_MESSAGE_CONTENT_TYPE = "message/rfc822"
RAW_MESSAGE_FILENAME = "message.eml"

# --- dropped-message correlation (RADD-1035) ---

#: `mail.dropped`'s `entity_id` is uuid5(this, Message-ID), so repeated drops of
#: one message correlate. Fixed value: the namespace IS the correlation key.
MAIL_DROPPED_ID_NAMESPACE = uuid.UUID("6d61696c-2d64-726f-7070-65640000002f")

#: `mail.dropped`'s reason for a message the poller could not parse (RADD-1035).
POLLER_PARSE_FAILURE_REASON = "unparseable message"

#: The mail-health card's window (RADD-1036) — notify's own age window is 24h too.
MAIL_HEALTH_WINDOW_HOURS = 24

#: `mail.failed` rows the health seam reads; the card says "500+" past it.
MAIL_HEALTH_SCAN_LIMIT = 500

#: How much of a delivery exception rides `mail.failed` (RADD-1036): enough for a
#: relay's 5xx line; the events table is not a log sink.
MAIL_ERROR_MAX_CHARS = 400

# Appended to the description when the sender matches no user (spec 47).
SENDER_NOTE_TEMPLATE = "{body}\n\n---\nReceived by email from {sender}"

# --- requester loop (spec 62) ---

# The outbound consumer's cursor name in the events stream.
OUTBOUND_CONSUMER_NAME = "mailintake.outbound"

# Events read per outbound poll iteration (mirrors googlechat's batch).
OUTBOUND_BATCH = 200

# The receipt's subject (RADD-1368): fixed, because its bracketed key threads the
# requester's replies (`parsing.extract_reply_key`); the body is `mail_ack_body`.
ACK_SUBJECT_TEMPLATE = "[{key}] {title}"

# Outbound reply to the contact when an agent leaves a PUBLIC comment.
REPLY_SUBJECT_TEMPLATE = "Re: [{key}] {title}"

# --- the resolution notice (RADD-982, back as a setting in RADD-1368) ---

# The `changes` diff token for a state move, as `csat.types` copies it.
STATE_CHANGE_FIELD = "state"

#: Pinned, not a `Re:` — a resolution opens a topic, like the CSAT survey.
RESOLVED_SUBJECT_TEMPLATE = "[{key}] Your request has been resolved"

#: `{state}` is where it landed: "Resolved" and "Closed" mean different things.
RESOLVED_BODY_TEMPLATE = (
    "Your request {key} — {title} — has been marked {state}.\n"
    "\n"
    "If it isn't sorted, reply to this email and the ticket picks up where it "
    "left off."
)

RESOLVED_REASON_TEMPLATE = "You are receiving this because you contacted us about {key}."

#: The csat plugin's id in the kernel registry, reached DEFERRED (`weak_depends`).
CSAT_PLUGIN_ID = "csat"

# The footer of an outbound reply: why the requester is being written to.
REPLY_REASON_TEMPLATE = (
    "You are receiving this because you contacted us about {key} — "
    "reply to this email to add to the ticket."
)
