"""Per-row send backoff for both email loops (RADD-997).

**The bug.** A failed send left the notification row exactly as the selection
had found it — unstamped, unread, recent — so the next tick selected it again.
The mailer ticks every `notify_mail_poll_interval` (5s) and the age window is
`notify_email_max_age_hours` (24h): one undeliverable row was worth ~17,000
delivery attempts, each an SMTP connection and, since RADD-960, a `mail.failed`
event written against the item. During the live incident that is what the relay
saw, per recipient, and Migadu rate-limited the sender.

**The fix is that a failure costs the row its place in the queue.** Two columns
carry it — `email_attempts` counts failures, `email_next_try` is the earliest
tick allowed to look at the row again — and both loops add one predicate to
their selection and one call to their failure branch. Nothing else in either
loop changes: what to send, to whom, and how the two channels dedup are
untouched.

**Giving up is a stamp.** Past the last rung the row is stamped `emailed_at`,
which is not a lie about having sent it but the existing vocabulary for "this
channel is finished with this row" — the same stamp an inactive recipient gets.
It has to be the stamp rather than a far-future `email_next_try`, because the
digest's selection is `emailed_at IS NULL`: leaving the row unstamped would hand
an address that has refused four times to the other loop to try again.

The ladder is a module constant rather than a setting because it is a policy
SHAPE, not an operator scalar — `config.py` holds the poll interval and the age
window, which is what an operator actually tunes. Four attempts spread over ~36
minutes replace 17,000 over 24 hours, and the row is still in the digest's reach
for most of that window if the relay recovers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# The mail module's vocabulary for "what does this failure mean", declared in
# notify's `weak_depends`. A wire enum, no runtime coupling: it is the value
# this module hands BACK to the transport, and inventing a second name for the
# same three answers is how two files come to disagree about what "silent"
# means.
from radd.modules.mailintake.types import MailFailureReport

from .models import Notification

#: How long to wait after the first, second and third consecutive failure. A
#: fourth failure exhausts the ladder and the row is given up on.
EMAIL_RETRY_DELAYS: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
)


def after_failure(attempts: int, now: datetime) -> datetime | None:
    """When the next attempt may run, or None to GIVE UP.

    `attempts` is the row's failure count BEFORE the failure being recorded, so
    0 is the first one and picks the first rung.
    """
    if attempts >= len(EMAIL_RETRY_DELAYS):
        return None
    return now + EMAIL_RETRY_DELAYS[attempts]


def is_terminal(attempts: int) -> bool:
    """Would the failure about to be recorded EXHAUST the ladder?

    `attempts` is the row's count BEFORE this failure, the argument
    `after_failure` takes, so the predicate is exactly "the next rung does not
    exist".
    """
    return attempts >= len(EMAIL_RETRY_DELAYS)


def failure_report(attempts: int) -> MailFailureReport:
    """What the transport should do with the failure about to happen (RADD-997,
    widened by RADD-1036).

    The first failure and the terminal one are emitted, and nothing in between.
    A `mail.failed` event drives automations and the activity feed, so it
    answers "did this person hear from us" — a question settled by the first
    failure and by the last, while the retries between them are this module's
    business and nobody else's. The live incident wrote one per recipient per
    five seconds into a stream every consumer reads.

    The terminal one is now DISTINGUISHED rather than merely emitted: giving up
    is the outcome an operator has to see (Settings → Monitoring counts it in
    red), and "a relay blipped once and the retry worked" is not the same news
    as "four attempts failed and this address will never be written to again".

    Asked BEFORE the attempt, because the answer decides what the transport is
    told to do with a failure that has not happened yet.
    """
    if is_terminal(attempts):
        return MailFailureReport.TERMINAL
    return MailFailureReport.REPORT if attempts == 0 else MailFailureReport.SILENT


def record_failure(row: Notification, now: datetime) -> bool:
    """Bank one failed send against `row`.

    Returns True when the ladder is exhausted and the caller must STAMP the row
    (the terminal give-up). Both loops call this so the two cannot drift into
    different retry policies for the same column pair.
    """
    next_try = after_failure(row.email_attempts, now)
    row.email_attempts += 1
    if next_try is None:
        return True
    row.email_next_try = next_try
    return False
