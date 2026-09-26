import uuid
from datetime import date

from pydantic import BaseModel

from radd.modules.workflow.types import StateCategory


class ThroughputBucket(BaseModel):
    """Items that ENTERED a done-category state within the bucket."""

    bucket: str  # bucket start date (ISO) — day, or the Monday of the ISO week
    count: int


class CumulativeFlowBucket(BaseModel):
    """The category distribution of items as of the bucket's end."""

    bucket: str
    counts: dict[str, int]  # StateCategory value -> count of items in it


class TimeInStateRow(BaseModel):
    """Average/median hours items spent in a category (completed segments only)."""

    category: StateCategory
    avg_hours: float
    median_hours: float
    sample: int  # number of completed segments measured


class CycleBrief(BaseModel):
    id: uuid.UUID
    name: str


class ReportScope(BaseModel):
    """Which projects a CROSS-PROJECT figure was actually computed over (RADD-789).

    A filtered LIST is visibly shorter. A filtered AVERAGE is just a different
    number, with nothing on the page saying so — two people looking at the same
    dashboard would read different velocities and have no way to tell why. So the
    figure carries its own scope and the header states it.

    `covered` is what the actor may read; `total` is how many projects the report
    nominally spans. Equal means the reader is seeing everything, and the UI says
    nothing at all — a label on every report would be noise that stops being read.
    """

    covered: list[str]  # project KEYS, sorted — what the number was computed from
    total: int  # projects on the instance

    @property
    def partial(self) -> bool:
        return len(self.covered) < self.total


class VelocityRow(BaseModel):
    # int for measure=count (exact pre-70 shape); a one-decimal float point sum
    # for measure=points (spec 70).
    cycle: CycleBrief
    completed: int | float  # items (or points) that entered done while assigned


class VelocityReport(BaseModel):
    rows: list[VelocityRow]
    scope: ReportScope


class CycleWindow(CycleBrief):
    start_date: date
    end_date: date


class BurnupPoint(BaseModel):
    # ints for measure=count; one-decimal float point sums for measure=points (spec 70).
    date: str  # the day (ISO)
    scope: int | float  # items (or points) assigned to the cycle as of end-of-day
    completed: int | float  # cumulative items (or points) completed by end-of-day


class BurnupSeries(BaseModel):
    cycle: CycleWindow
    series: list[BurnupPoint]
    scope: ReportScope
