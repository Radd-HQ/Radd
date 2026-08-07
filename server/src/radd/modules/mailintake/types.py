"""Wire constants for the email-to-issue intake (spec 47) and the requester
feedback loop — contacts, acks, outbound replies (spec 62)."""

from datetime import timedelta
from enum import StrEnum


class MailEntity(StrEnum):
    MAIL = "mail_intake"
    CONTACT = "mail_contact"
    MESSAGE = "mail_message"
    SOURCE = "mail_source"
    SENDER = "mail_sender"


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
# replies back onto the item (parsing.extract_reply_key).
ACK_SUBJECT_TEMPLATE = "[{key}] {title}"
ACK_BODY_TEMPLATE = (
    "Your request has been received and is being tracked as {key}.\n"
    "\n"
    "We'll follow up by email. You can reply to this message to add details —\n"
    "replies are attached to the ticket automatically (keep [{key}] in the subject).\n"
)

# Outbound reply to the contact when an agent leaves a PUBLIC comment.
REPLY_SUBJECT_TEMPLATE = "Re: [{key}] {title}"
