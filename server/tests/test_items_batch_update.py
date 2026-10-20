"""`PATCH /items` is all or nothing (RADD-1505).

The invariant every batched writer leans on: a refusal on one patch leaves the
others unwritten too, and the refusal names the item. The roadmap's Save used
to be a per-item loop that stopped at the first failure — some children saved,
the epic never.
"""

from datetime import date

import pytest

from _factories import make_project
from radd.exceptions import ConflictError
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemBatchPatch, ItemBatchUpdate, ItemCreate, ItemUpdate


def _dates(start: date, target: date) -> ItemUpdate:
    return ItemUpdate(start_date=start, target_date=target)


async def test_a_batch_writes_every_patch(db, admin):
    project = await make_project(db, "BA", actor=admin)
    first = await items.create_item(db, ItemCreate(project_id=project.id, title="first"), admin)
    second = await items.create_item(db, ItemCreate(project_id=project.id, title="second"), admin)

    updated = await items.update_items(
        db,
        ItemBatchUpdate(
            patches=[
                ItemBatchPatch(item_id=first.id, patch=_dates(date(2026, 9, 1), date(2026, 9, 5))),
                ItemBatchPatch(item_id=second.id, patch=_dates(date(2026, 9, 6), date(2026, 9, 9))),
            ]
        ),
        actor=admin,
    )

    assert [row.id for row in updated] == [first.id, second.id]
    assert (await items.get_item(db, first.id, admin)).start_date == date(2026, 9, 1)
    assert (await items.get_item(db, second.id, admin)).target_date == date(2026, 9, 9)


async def test_one_refusal_rolls_the_whole_batch_back_and_names_the_item(db, admin):
    project = await make_project(db, "BR", actor=admin)
    first = await items.create_item(db, ItemCreate(project_id=project.id, title="first"), admin)
    second = await items.create_item(db, ItemCreate(project_id=project.id, title="second"), admin)
    batch = ItemBatchUpdate(
        patches=[
            ItemBatchPatch(item_id=first.id, patch=_dates(date(2026, 9, 1), date(2026, 9, 5))),
            # Inverted span: the date rule refuses this one.
            ItemBatchPatch(item_id=second.id, patch=_dates(date(2026, 9, 9), date(2026, 9, 1))),
        ]
    )

    # The request transaction, as `get_session` runs it: rolled back on error.
    request = await db.begin_nested()
    with pytest.raises(ConflictError) as refused:
        await items.update_items(db, batch, actor=admin)
    await request.rollback()

    assert str(refused.value).startswith(f"{second.key}: ")
    assert (await items.get_item(db, first.id, admin)).start_date is None, (
        "the first patch survived a refusal on the second"
    )
