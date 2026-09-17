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


class MailFailureReport(StrEnum):
    """What the transport should do with a delivery failure (RADD-997/1036).

    It replaces the `emit_failure` boolean, which could say "emit" or "don't"
    and had no way to say the third thing an operator actually needs to know:
    that a retry ladder RAN OUT and nobody will hear from us. Settings →
    Monitoring counts those separately from the first blip of a send that
    recovered a minute later, and a second boolean beside the first would have
    made "silent AND terminal" expressible, which is nonsense.

    * `REPORT` — emit `mail.failed`. The send is over the moment it fails: a
      reply, an acknowledgement, a survey, an automation's email. The default,
      and right for everyone who is not running a ladder.
    * `SILENT` — a retry is coming, so the question the event answers ("did
      this person hear from us?") is not settled yet. The live incident wrote
      one event per recipient per five seconds into a stream every consumer
      reads.
    * `TERMINAL` — the last rung. Emitted, and marked given-up in the payload.
    """

    REPORT = "report"
    SILENT = "silent"
    TERMINAL = "terminal"


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


class MailRuleStatus(StrEnum):
    """What ONE rule did on ONE message (RADD-989) — the dry run's vocabulary.

    The distinction the preview exists for: a rule that ran and did not claim the
    message (DECLINED) and a rule that crashed and was skipped (ERRORED) both
    leave the chain continuing, and reporting them the same way is how a broken
    rule reads as a working one. `feature_enabled` raising for an unregistered
    feature was invisible for a release precisely because its outcome rendered as
    "no rule matched — source default".

    **The last two exist so that ABSENCE means one thing** (RADD-994). The trace
    used to hold only the rules the walk consulted, which is three different
    stories told as the same silence: a rule switched off, a rule sitting below
    the winner, and a rule that was deleted all rendered as "not in the list".
    "Why didn't my rule fire" is the commonest routing question there is, and the
    honest answer for two of those three is a row, not a gap.
    """

    MATCHED = "matched"
    DECLINED = "declined"
    ERRORED = "errored"
    DISABLED = "disabled"        # switched off — the walk skipped it (RADD-994)
    NOT_REACHED = "not_reached"  # an earlier rule matched and stopped the chain


#: The extra choice every llm rule offers the model on top of its own answers
#: (RADD-989). Without it "none of these apply" is inexpressible: the model must
#: pick from an enumerated list, so an off-topic email forces a wrong category and
#: the source default becomes reachable only by FAILURE. With it, declining is a
#: verdict — and one the dry run can name. Appended at ask time, never stored as
#: an answer row, so it cannot be edited into meaning something else.
NO_MATCH_ANSWER = "None of these"


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

#: When a cap above drops later parts, `parsing` reports HOW MANY and `intake`
#: leaves this note on the item (RADD-1035). A silent drop is exactly what the
#: cap must not be: someone whose fourth screenshot vanished has no way to know
#: the desk never got it. The note is a SYSTEM comment because the item — the
#: place a note can live — only exists in `intake`.
ATTACHMENTS_DROPPED_NOTE = (
    "{count} attachment(s) on the inbound email were not stored — the message hit "
    "Radd's per-message attachment cap ({max_count} files / {max_mb} MB). Ask the "
    "sender to resend the rest as separate, smaller emails if they are needed."
)

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

# --- sender authentication (RADD-1032) ---

#: RFC 8601 result tokens. `pass` is the only value that proves a method
#: authenticated; everything in FAIL is a positive statement that it did NOT.
#: `none`/`neutral` (not published / not evaluated) are neither — a message with
#: only those has proved nothing, which the caller treats as unverified too.
AUTH_PASS_RESULT = "pass"
AUTH_FAIL_RESULTS = frozenset({"fail", "softfail", "hardfail", "permerror", "temperror"})
#: The three methods a trusted authserv-id verdict is read for. Radd is trusting
#: its MX's stamp, not verifying crypto itself, so this is the whole vocabulary.
AUTH_METHODS = ("dkim", "spf", "dmarc")

#: When a source trusts an authserv-id and the message FAILS or OMITS that
#: verdict, attribution is demoted to SYSTEM and the reader is told why. `From:`
#: is forgeable end to end, so a demoted message is recorded exactly as received
#: but attributed to nobody — a forged staff `From:` can no longer speak as that
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

#: How long a webhook/poller-ingested message's RAW bytes are kept, so an
#: over-eager quote strip or a lost attachment is recoverable. `0` = do not
#: retain (the privacy-conscious choice — some desks must not keep customer mail
#: at rest). 30 days is longer than any provider's retry window and short enough
#: that the blob store is not the archive of every message ever received. A
#: retention SWEEP that deletes bytes past this age is a separate follow-up; this
#: constant is what it will read.
MAIL_RAW_RETENTION_DAYS = 30

#: The raw message is stored as one loose blob through the spec-102 seam.
RAW_MESSAGE_CONTENT_TYPE = "message/rfc822"
RAW_MESSAGE_FILENAME = "message.eml"

# --- dropped-message correlation (RADD-1035) ---

#: `mail.dropped` events key their `entity_id` off the inbound Message-ID via
#: uuid5 in this namespace, so two deliveries of the SAME dropped message
#: correlate to one id instead of scattering across a fresh uuid4 each time. A
#: message with no id (or an unparseable one) has nothing to correlate on and
#: falls back to uuid4. Fixed value: the namespace IS the correlation key.
MAIL_DROPPED_ID_NAMESPACE = uuid.UUID("6d61696c-2d64-726f-7070-65640000002f")

#: The reason string on a `mail.dropped` a poller emits for a message it could
#: not parse (RADD-1035) — so the loss is on the queryable event stream, not only
#: in a log line the poller then forgets by flagging the message Seen.
POLLER_PARSE_FAILURE_REASON = "unparseable message"

#: The window Settings → Monitoring's mail-health card reports over (RADD-1036).
#: A day, because that is the shape of the question an operator is asking —
#: "is mail working right now" — and because notify's own age window is 24h, so
#: a failure older than this has already been given up on by the loops too.
MAIL_HEALTH_WINDOW_HOURS = 24

#: How many `mail.failed` rows the health seam reads. A healthy instance has
#: zero and a broken one only needs to be told it is broken, so the card reports
#: "500+" rather than making an operator wait on a full-window scan. The count
#: is capped, never wrong: the seam says when it hit the cap.
MAIL_HEALTH_SCAN_LIMIT = 500

#: How much of a delivery exception rides the `mail.failed` payload (RADD-1036).
#: Enough for "Connection refused" or a relay's 5xx line — which is the whole
#: reason the card exists — and capped because an SMTP server may answer with a
#: paragraph, and the events table is not a log sink.
MAIL_ERROR_MAX_CHARS = 400

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
# SUBJECT stays a fixed wire constant here. The BODY used to live beside it in
# `radd.mailrender` as a second constant (RADD-967); since RADD-1045 it is the
# `mail_ack_body` scalar-cascade setting (Settings → Email, default text on
# `config.Settings.mail_ack_body`) — policy this module owns and resolves in
# `service.send_ack`, not a rendering decision `mailrender` gets to make.
ACK_SUBJECT_TEMPLATE = "[{key}] {title}"

# Outbound reply to the contact when an agent leaves a PUBLIC comment.
REPLY_SUBJECT_TEMPLATE = "Re: [{key}] {title}"

# --- the resolution notice (RADD-982) ---

# The `changes` diff token for a state move (`items/changes.py`'s `scalar("state", …)`).
# Copied rather than imported, exactly as `csat.types` copies it: `items` exports no
# name for it, and a second reader of the diff should not be the reason it gains one.
STATE_CHANGE_FIELD = "state"

#: Its own sentence, not a `Re:` on the requester's — the resolution OPENS a topic
#: the way the CSAT survey does, so `send_item_mail` is asked to pin it. Threading
#: is untouched: In-Reply-To/References still come from the message store, so a
#: client still files this under the ticket's conversation.
RESOLVED_SUBJECT_TEMPLATE = "[{key}] Your request has been resolved"

#: What the notice says. `{state}` is the state it actually landed in, because a
#: desk with "Resolved" and "Closed" means two different things by them and the
#: requester is the one person who cannot look the difference up.
RESOLVED_BODY_TEMPLATE = (
    "Your request {key} — {title} — has been marked {state}.\n"
    "\n"
    "If it isn't sorted, reply to this email and the ticket picks up where it "
    "left off."
)

#: The notice's footer — the same "why am I getting this" wording as a reply,
#: pointed at the end of the conversation rather than the middle of it.
RESOLVED_REASON_TEMPLATE = (
    "You are receiving this because you contacted us about {key}."
)

#: The csat plugin's id in the kernel registry. mailintake reaches it DEFERRED and
#: feature-detected (`weak_depends`), so a disabled or uninstalled csat means "not
#: announcing" rather than an ImportError — the `ai` seam's shape (RADD-961).
CSAT_PLUGIN_ID = "csat"

# Why each recipient is being written to — the footer of an outbound reply.
REPLY_REASON_TEMPLATES = {
    MailRecipientKind.WATCHER: "You are watching {key} — reply to this email to comment.",
    MailRecipientKind.REQUESTER: (
        "You are receiving this because you contacted us about {key} — "
        "reply to this email to add to the ticket."
    ),
}
