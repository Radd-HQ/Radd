"""Per-row send backoff shared by both email loops (RADD-997).

A failed send used to stay selectable on the next 5-second tick for the whole
24-hour age window. Each failure now bumps `email_attempts` and sets
`email_next_try`; past the last rung the row is DROPPED (`delivery`, not a
far-future retry), because the digest selects the rows still owed an answer and
would otherwise retry an address that already refused four times. The ladder
is a module constant: a policy shape, not an operator knob.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import Notification

from .transport import MailFailureReport

#: How long to wait after the first, second and third consecutive failure. A
#: fourth failure exhausts the ladder and the row is given up on.
EMAIL_RETRY_DELAYS: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
)


def is_terminal(attempts: int) -> bool:
    """Would the failure about to be recorded EXHAUST the ladder? `attempts` is
    the row's count BEFORE this failure."""
    return attempts >= len(EMAIL_RETRY_DELAYS)


def after_failure(attempts: int, now: datetime) -> datetime | None:
    """When the next attempt may run (count BEFORE this failure), or None to GIVE UP."""
    if is_terminal(attempts):
        return None
    return now + EMAIL_RETRY_DELAYS[attempts]


def failure_report(attempts: int) -> MailFailureReport:
    """What the transport should do with the failure about to happen: REPORT the
    first, TERMINAL the last, SILENT the retries between — `mail.failed` answers
    "did this person hear from us", which only those two settle. Asked BEFORE
    the attempt."""
    if is_terminal(attempts):
        return MailFailureReport.TERMINAL
    return MailFailureReport.REPORT if attempts == 0 else MailFailureReport.SILENT


def record_failure(row: Notification, now: datetime) -> bool:
    """Bank one failed send against `row`; True = exhausted, the caller DROPS
    it. Shared so the two loops cannot drift."""
    next_try = after_failure(row.email_attempts, now)
    row.email_attempts += 1
    if next_try is None:
        return True
    row.email_next_try = next_try
    return False
