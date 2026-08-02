"""Shared Pydantic field types for API schemas.

`UtcDatetime` serializes to ISO-8601 with a `Z` suffix. Our datetime columns are
naive UTC (see `auth.security.utcnow`); without the suffix a browser's
`new Date("2026-07-20T09:49:40")` parses the string as LOCAL time, skewing every
timestamp by the viewer's UTC offset (the "4 hours ago" bug). Tagging naive
values as UTC on the way out makes them unambiguous for every client.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def _to_utc_z(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


# Use in schemas instead of bare `datetime`. json-only so Python-mode dumps
# (internal reuse) still yield a datetime object.
UtcDatetime = Annotated[datetime, PlainSerializer(_to_utc_z, return_type=str, when_used="json")]
