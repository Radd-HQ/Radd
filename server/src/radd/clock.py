"""One clock (RADD-897): every schema DateTime is timezone-NAIVE UTC, so every Python-side
stamp comes from `utcnow()` — never a module's private helper."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC now — matches the schema's timezone-naive DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)
