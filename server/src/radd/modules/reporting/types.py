from enum import StrEnum

# The /reports/velocity `last` bound (a velocity dashboard widget shares it).
VELOCITY_MAX_LAST = 50


class ReportInterval(StrEnum):
    """Bucket width for the time-series reports (throughput, cumulative flow)."""

    DAY = "day"
    WEEK = "week"


class ReportMeasure(StrEnum):
    """What velocity/burnup count (spec 70): items, or story-point sums (null = 0)."""

    COUNT = "count"
    POINTS = "points"
