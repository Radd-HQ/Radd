"""Shared Pydantic field types + wire constants for API schemas.

`UtcDatetime` serializes naive-UTC columns (`radd.clock.utcnow`) with a `Z` suffix: without
it a browser parses the string as LOCAL time (the "4 hours ago" bug)."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def _to_utc_z(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


# Use in schemas instead of bare `datetime`. json-only so Python-mode dumps
# (internal reuse) still yield a datetime object.
UtcDatetime = Annotated[datetime, PlainSerializer(_to_utc_z, return_type=str, when_used="json")]

# Header carrying the pre-pagination row count on list endpoints that accept
# `limit`/`offset` (RADD-883). Set only when `limit` was passed — an unpaged
# request already holds the full list.
TOTAL_COUNT_HEADER = "X-Total-Count"
