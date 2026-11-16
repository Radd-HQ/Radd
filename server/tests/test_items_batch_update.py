"""`PATCH /items` is all or nothing (RADD-1505).

The invariant every batched writer leans on: a refusal on one patch leaves the
others unwritten too, and the refusal names the item. The roadmap's Save used
to be a per-item loop that stopped at the first failure — some children saved,
the epic never.
"""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from _factories import make_project
from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.fields.validation import FieldValidationError
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


async def test_a_field_refusal_names_the_item_in_the_list_its_handler_renders(db, admin):
    """The 422 handlers send `exc.errors`, not the message (RADD-1542): a key only
    in `args` reached the log and never the person looking at the Save button."""
    project = await make_project(db, "BF", actor=admin)
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="only"), admin)
    batch = ItemBatchUpdate(
        patches=[
            ItemBatchPatch(item_id=item.id, patch=ItemUpdate(custom_fields={"no_such_field": 1}))
        ]
    )

    request = await db.begin_nested()
    with pytest.raises(FieldValidationError) as refused:
        await items.update_items(db, batch, actor=admin)
    await request.rollback()

    assert refused.value.errors, "the refusal carries no failure list"
    assert all(failure.startswith(f"{item.key}: ") for failure in refused.value.errors)


async def test_a_missing_item_is_not_named(db, admin):
    """Prefixing a key onto a not-found would confirm an item the caller cannot see."""
    batch = ItemBatchUpdate(
        patches=[ItemBatchPatch(item_id=uuid.uuid4(), patch=_dates(date(2026, 9, 1), date(2026, 9, 5)))]
    )
    request = await db.begin_nested()
    with pytest.raises(NotFoundError) as refused:
        await items.update_items(db, batch, actor=admin)
    await request.rollback()
    assert ": " not in str(refused.value), "a key was prefixed onto a not-found"


def test_the_batch_takes_a_whole_plan_and_no_more():
    """A plan verb drafts every loaded child of an epic; Save must take it whole
    (RADD-1542: the cap was the 500 of bulk edit, under what the roadmap loads)."""
    patch = ItemUpdate(start_date=date(2026, 9, 1))

    def batch(count: int) -> ItemBatchUpdate:
        return ItemBatchUpdate(
            patches=[ItemBatchPatch(item_id=uuid.uuid4(), patch=patch) for _ in range(count)]
        )

    assert settings.items_batch_patch_max > settings.bulk_max_items
    assert len(batch(settings.items_batch_patch_max).patches) == settings.items_batch_patch_max
    with pytest.raises(ValidationError):
        batch(settings.items_batch_patch_max + 1)
