"""Wire constants for the email-to-issue intake (spec 47) and the requester
feedback loop — contacts, acks, outbound replies (spec 62)."""

from enum import StrEnum


class MailEntity(StrEnum):
    MAIL = "mail_intake"
    CONTACT = "mail_contact"


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
