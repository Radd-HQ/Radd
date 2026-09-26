"""Shared schedule preview contract and arithmetic, with no module or HTTP policy.

Owners authenticate/authorize their endpoint and pass the configured timezone.
The same next_run function drives both live schedulers and these previews.
"""
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from radd.apitypes import UtcDatetime
from radd import schedule

class SchedulePreviewRequest(BaseModel):
    """A candidate schedule, not necessarily a valid one — the point of the
    endpoint is to say WHY when it is not, so this deliberately does not reuse
    `ScheduleConfig` (whose validator would 422 with pydantic's wrapping before
    the handler could phrase the answer)."""

    kind: str
    minutes: int | None = None
    time: str | None = Field(default=None, max_length=10)
    weekdays: list[int] | None = None
    day: int | None = None
    expression: str | None = Field(default=None, max_length=200)


class SchedulePreviewRead(BaseModel):
    """The next few occurrences, or the reason there are none."""

    timezone: str
    next_runs: list[UtcDatetime] = []
    error: str | None = None



def preview_schedule(data: SchedulePreviewRequest, timezone: str, *, now: datetime | None = None) -> SchedulePreviewRead:
    cfg = data.model_dump(exclude_none=True)
    try:
        schedule.validate_config(cfg)
        at = now if now is not None else datetime.now(UTC).replace(tzinfo=None)
        runs = []
        for _ in range(5):
            at = schedule.next_run(cfg, at, timezone)
            runs.append(at)
    except ValueError as exc:
        return SchedulePreviewRead(timezone=timezone, error=str(exc))
    return SchedulePreviewRead(timezone=timezone, next_runs=runs)
