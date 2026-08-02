"""Wire constants for CSAT satisfaction surveys (spec 65)."""

from enum import StrEnum


class CsatEvent(StrEnum):
    # Both emitted with entity_type=item so they land in the item's History feed
    # (sla.breached precedent) and with actor_id=None so automation rules on them
    # fire (the engine skips SYSTEM-actor events as its loop guard).
    REQUESTED = "csat.requested"
    RESPONDED = "csat.responded"


class CsatEntity(StrEnum):
    SURVEY = "csat_survey"


# The sender's cursor name in the events stream (consumer-offset pattern).
CONSUMER_NAME = "csat.sender"

# Events read per sender poll iteration (mirrors mailintake's outbound batch).
BATCH = 200

# The `changes` diff token for a state move (items/changes.py `diff_item_reads`).
STATE_CHANGE_FIELD = "state"

# Rating scale — the five links in the email and the public submit bounds.
RATING_MIN = 1
RATING_MAX = 5

# Free-text comment cap on the public submit (spec 65).
COMMENT_MAX_CHARS = 2000

# Comment excerpt carried on the csat.responded payload (comments precedent —
# the stream is trusted, but payloads stay compact).
PAYLOAD_COMMENT_EXCERPT_CHARS = 200

# The survey email: subject threads like the ack/reply mails ([KEY] prefix);
# each rating is one click into the PUBLIC SPA page, which does the POST — a
# mail scanner prefetching the links can never record a rating.
SURVEY_SUBJECT_TEMPLATE = "[{key}] How did we do?"
SURVEY_BODY_TEMPLATE = (
    "Your request {key} — {title} — has been resolved.\n"
    "\n"
    "How satisfied are you with how it was handled? One click records your rating:\n"
    "\n"
    "{links}\n"
    "\n"
    "You can also leave a comment on the rating page. Thanks for your feedback!\n"
)
RATING_LINK_TEMPLATE = "  {label}: {base_url}/public/csat/{token}?rating={rating}"
RATING_LABELS: dict[int, str] = {
    1: "1 · Very dissatisfied",
    2: "2 · Dissatisfied",
    3: "3 · Neutral",
    4: "4 · Satisfied",
    5: "5 · Very satisfied",
}
