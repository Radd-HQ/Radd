"""One clock (RADD-897).

`utcnow()` is THE schema timestamp convention: every DateTime column in the
schema is timezone-NAIVE and holds UTC wall-clock time, so every Python-side
stamp must be produced the same way. Before this module the expression
`datetime.now(UTC).replace(tzinfo=None)` was hand-copied ~30 times (15 private
`_utcnow`/`_now` helpers plus inline copies) — the convention of the entire
schema, defined once here instead.

Kernel-adjacent on purpose (like `QueryError`): modules import `radd.clock`,
never each other's private helpers.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC now — matches the schema's timezone-naive DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)
