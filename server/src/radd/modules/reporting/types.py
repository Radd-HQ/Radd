from enum import StrEnum


class ReportInterval(StrEnum):
    """Bucket width for the time-series reports (throughput, cumulative flow)."""

    DAY = "day"
    WEEK = "week"


class ReportMeasure(StrEnum):
    """What velocity/burnup count (spec 70): items, or story-point sums (null = 0)."""

    COUNT = "count"
    POINTS = "points"
