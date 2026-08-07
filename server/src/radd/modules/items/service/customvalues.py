"""Bulk rewrites of ONE custom field's stored values (RADD-949).

Custom-field values live in `work_items.custom_fields` (JSONB, keyed by the
field's registry key), and that table is `items`'. So when `fields` removes a
select option it cannot go and fix the items itself — rule 1 — and this is the
public seam it calls instead. `fields` declares `weak_depends=("items",)` for the
reach, because `items` already depends on `fields` and a hard edge would be a
cycle.

Set-based, not a loop: one statement for single-selects and one for multi, each
touching only the rows that actually carry the value. A field with an option on
90k items must not become 90k round trips.

Nothing here validates — the caller owns the decision about what the replacement
should be, and it is the only place that knows whether the field is required.
"""

from __future__ import annotations

from sqlalchemy import cast, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WorkItem


async def count_with_value(session: AsyncSession, field_key: str, value: str) -> int:
    """How many items carry `value` for this field, either shape.

    Exists so the UI can ASK the question with the number in it — "move the 4
    items on Legacy to…" — rather than making someone accept a migration whose
    size they cannot see.
    """
    scalar = WorkItem.custom_fields[field_key].astext == value
    contains = WorkItem.custom_fields[field_key].contains(cast([value], JSONB))
    return int(
        await session.scalar(select(func.count()).select_from(WorkItem).where(scalar | contains))
        or 0
    )


async def migrate_custom_field_value(
    session: AsyncSession, field_key: str, old: str, new: str | None
) -> int:
    """Repoint every item storing `old` for `field_key`.

    `new=None` clears the key entirely, which is what "leave it empty" means for
    an optional field — storing JSON null instead would leave a value that is
    neither absent nor valid, and every reader would have to know the difference.

    Returns the number of rows touched.
    """
    scalar_rows = await session.execute(
        update(WorkItem)
        .where(WorkItem.custom_fields[field_key].astext == old)
        .values(
            custom_fields=(
                WorkItem.custom_fields.op("-")(field_key)
                if new is None
                else WorkItem.custom_fields.concat(
                    func.jsonb_build_object(field_key, cast(new, JSONB))
                )
            )
        )
    )
    return scalar_rows.rowcount or 0


async def drop_from_multi_select(
    session: AsyncSession, field_key: str, value: str
) -> int:
    """Remove `value` from each item's list for `field_key`.

    A multi_select needs no replacement: a shorter list is still a valid one.
    The array is rebuilt rather than filtered in place because JSONB has no
    element-delete-by-value — `jsonb_agg` over the surviving elements is the
    only single-statement form, and `COALESCE` covers the item whose list is
    emptied (jsonb_agg over no rows is NULL, which would write a null value).
    """
    result = await session.execute(
        update(WorkItem)
        .where(WorkItem.custom_fields[field_key].contains(cast([value], JSONB)))
        .values(
            custom_fields=WorkItem.custom_fields.concat(
                func.jsonb_build_object(
                    field_key,
                    # `CAST(:p AS text)`, not `:p::text` — SQLAlchemy's text()
                    # parser reads the second colon of `::` as the start of
                    # another bind name and then reports the first one as
                    # undefined, which is a confusing way to learn this.
                    text(
                        "COALESCE((SELECT jsonb_agg(elem) FROM jsonb_array_elements("
                        "work_items.custom_fields -> :cv_key) AS elem "
                        "WHERE elem <> to_jsonb(CAST(:cv_value AS text))), CAST('[]' AS jsonb))"
                    ).bindparams(cv_key=field_key, cv_value=value),
                )
            )
        )
    )
    return result.rowcount or 0
