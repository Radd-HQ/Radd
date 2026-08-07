"""Removing a select option, and what happens to the items holding it (RADD-949).

`extend_options` was additive because removal is dangerous — items already store
the value and would silently become invalid. That is an argument for forcing the
caller to say what happens to them, which is what `remove_option` does, and the
invariant worth pinning is the one the argument was about: **no item is left
storing a value its field no longer offers.**

The rewrites are set-based JSONB statements rather than a read-modify-write loop,
so they are exactly the kind of code that looks right and does nothing (a `->`
where `->>` was meant matches no rows and reports success). Every case here
asserts the item's stored value afterwards, never the return count alone.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.fields.validation import FieldValidationError
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    suffix = uuid.uuid4().hex[:8]
    actor = User(
        email=f"fo-{suffix}@example.com", name="Fields", instance_role=InstanceRole.ADMIN.value
    )
    db.add(actor)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"FO{suffix[:4].upper()}", name="Field options")
    )
    return actor, project, suffix


async def _field(db, suffix, *, kind, required=False, options, default=None):
    return await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            key=f"sel_{suffix}_{kind.value}_{uuid.uuid4().hex[:4]}",
            name="Bucket",
            type=kind,
            options=options,
            required=required,
            default_value=default,
        ),
    )


async def _item(db, project, actor, field, value):
    return await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="carrier", custom_fields={field.key: value}),
        actor,
    )


async def _stored(db, item_id, key):
    row = await db.scalar(select(WorkItem.custom_fields).where(WorkItem.id == item_id))
    return (row or {}).get(key, "<<absent>>")


# --- single select ---------------------------------------------------------------


async def test_a_required_field_moves_its_items_to_the_named_option(db, world):
    actor, project, suffix = world
    field = await _field(
        db, suffix, kind=FieldType.SELECT, required=True, options=["Legacy", "Current"]
    )
    one = await _item(db, project, actor, field, "Legacy")
    untouched = await _item(db, project, actor, field, "Current")

    moved = await fields_service.remove_option(
        db, field.id, "Legacy", replace_with="Current", actor_id=actor.id
    )

    assert moved == 1
    assert await _stored(db, one.id, field.key) == "Current"
    assert await _stored(db, untouched.id, field.key) == "Current"
    assert (await fields_service.get_field(db, field.id)).options == ["Current"]


async def test_a_required_field_refuses_to_clear(db, world):
    """Clearing would leave items violating their own field — the exact invalid
    state this function exists to prevent."""
    actor, project, suffix = world
    field = await _field(
        db, suffix, kind=FieldType.SELECT, required=True, options=["Legacy", "Current"]
    )
    await _item(db, project, actor, field, "Legacy")

    with pytest.raises(FieldValidationError):
        await fields_service.remove_option(db, field.id, "Legacy", replace_with=None)


async def test_an_optional_field_may_clear_and_the_key_goes_away(db, world):
    """Absent, not JSON null: a null would be neither missing nor valid, and
    every reader would have to know the difference."""
    actor, project, suffix = world
    field = await _field(db, suffix, kind=FieldType.SELECT, options=["Legacy", "Current"])
    one = await _item(db, project, actor, field, "Legacy")

    await fields_service.remove_option(db, field.id, "Legacy", replace_with=None)

    assert await _stored(db, one.id, field.key) == "<<absent>>"


async def test_the_replacement_cannot_be_the_option_being_removed(db, world):
    actor, project, suffix = world
    field = await _field(
        db, suffix, kind=FieldType.SELECT, required=True, options=["Legacy", "Current"]
    )
    with pytest.raises(FieldValidationError):
        await fields_service.remove_option(db, field.id, "Legacy", replace_with="Legacy")


async def test_removing_the_last_option_is_refused(db, world):
    _, _, suffix = world
    field = await _field(db, suffix, kind=FieldType.SELECT, options=["Only"])
    with pytest.raises(FieldValidationError):
        await fields_service.remove_option(db, field.id, "Only", replace_with=None)


# --- multi select ----------------------------------------------------------------


async def test_a_multi_select_just_gets_shorter(db, world):
    actor, project, suffix = world
    field = await _field(
        db, suffix, kind=FieldType.MULTI_SELECT, options=["a", "b", "c"]
    )
    both = await _item(db, project, actor, field, ["a", "b"])
    only = await _item(db, project, actor, field, ["b"])

    await fields_service.remove_option(db, field.id, "a")

    assert await _stored(db, both.id, field.key) == ["b"]
    assert await _stored(db, only.id, field.key) == ["b"]


async def test_a_multi_select_item_left_with_nothing_holds_an_empty_list(db, world):
    """`jsonb_agg` over no surviving elements is NULL, which would write a null
    where a list belongs — the COALESCE in the statement is what stops it."""
    actor, project, suffix = world
    field = await _field(db, suffix, kind=FieldType.MULTI_SELECT, options=["a", "b"])
    lone = await _item(db, project, actor, field, ["a"])

    await fields_service.remove_option(db, field.id, "a")

    assert await _stored(db, lone.id, field.key) == []


# --- the default nobody would think to check --------------------------------------


async def test_a_default_naming_the_removed_option_does_not_survive(db, world):
    """It would seed the dead value onto every item created afterwards — the
    same invalidity, one level up."""
    _, _, suffix = world
    field = await _field(
        db,
        suffix,
        kind=FieldType.SELECT,
        required=True,
        options=["Legacy", "Current"],
        default="Legacy",
    )

    await fields_service.remove_option(db, field.id, "Legacy", replace_with="Current")

    assert (await fields_service.get_field(db, field.id)).default_value == "Current"


async def test_a_multi_select_default_drops_just_that_value(db, world):
    _, _, suffix = world
    field = await _field(
        db, suffix, kind=FieldType.MULTI_SELECT, options=["a", "b"], default=["a", "b"]
    )

    await fields_service.remove_option(db, field.id, "a")

    assert (await fields_service.get_field(db, field.id)).default_value == ["b"]


# --- the dry run the dialog asks with ---------------------------------------------


async def test_usage_counts_both_shapes(db, world):
    actor, project, suffix = world
    single = await _field(db, suffix, kind=FieldType.SELECT, options=["x", "y"])
    multi = await _field(db, suffix, kind=FieldType.MULTI_SELECT, options=["x", "y"])
    await _item(db, project, actor, single, "x")
    await _item(db, project, actor, single, "y")
    await _item(db, project, actor, multi, ["x", "y"])

    assert await fields_service.option_usage(db, single.id, "x") == 1
    assert await fields_service.option_usage(db, multi.id, "x") == 1
    assert await fields_service.option_usage(db, single.id, "y") == 1


async def test_an_unknown_option_is_refused_rather_than_silently_succeeding(db, world):
    _, _, suffix = world
    field = await _field(db, suffix, kind=FieldType.SELECT, options=["a", "b"])
    with pytest.raises(FieldValidationError):
        await fields_service.remove_option(db, field.id, "nope", replace_with="a")
