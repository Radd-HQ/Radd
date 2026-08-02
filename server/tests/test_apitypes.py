"""UtcDatetime serializes API timestamps as UTC with a `Z` suffix (the fix for
the 'everything is 4 hours ago' bug — naive strings were parsed as browser-local)."""

from datetime import UTC, datetime, timedelta, timezone

from pydantic import BaseModel

from radd.apitypes import UtcDatetime


class M(BaseModel):
    at: UtcDatetime
    maybe: UtcDatetime | None = None


def test_naive_is_tagged_utc_with_z():
    dumped = M(at=datetime(2026, 7, 20, 9, 49, 40)).model_dump(mode="json")
    assert dumped["at"] == "2026-07-20T09:49:40Z"
    assert dumped["maybe"] is None


def test_aware_offset_converted_to_utc_z():
    # 07:33-04:00 == 11:33 UTC
    aware = datetime(2024, 5, 9, 7, 33, 54, tzinfo=timezone(timedelta(hours=-4)))
    assert M(at=aware).model_dump(mode="json")["at"] == "2024-05-09T11:33:54Z"


def test_python_mode_keeps_datetime():
    # json-only serializer: internal reuse still gets a real datetime, not a string
    value = M(at=datetime(2026, 1, 1, tzinfo=UTC)).model_dump()["at"]
    assert isinstance(value, datetime)
