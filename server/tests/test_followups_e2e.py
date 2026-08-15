"""End-to-end wiring for the settings/UX follow-ups, driven through the
real services against live Postgres in a rolled-back transaction (nothing persists):

- field default_value is seeded onto items that omit the key (spec 50 follow-up),
- issue #[…] mentions become derived `mentions` backlinks (spec 52 follow-up),
- timelog_hours_per_day resolves through the scalar cascade (spec 50 follow-up).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate, FieldDefinitionUpdate
from radd.modules.fields.types import FieldType
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemLinkType
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.timelogging import enablement, service as timelog_service
from radd.modules.timelogging.schemas import EstimateSet
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
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
async def admin(db) -> User:
    user = User(
        email=f"fu-{uuid.uuid4().hex[:8]}@example.com",
        name="Followup Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db) -> Project:
    return await projects_service.create_project(
        db, ProjectCreate(key="FUX", name="Followups X")
    )


# --- field default values ---


async def test_default_value_seeded_when_key_omitted(db, admin, project):
    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id],
            key="priority_band",
            name="Priority band",
            type=FieldType.SELECT,
            options=["p1", "p2", "p3"],
            default_value="p2",
        ),
        actor_id=admin.id,
    )

    # Omit the field on create → the default lands.
    seeded = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="no band given"), admin
    )
    assert seeded.custom_fields.get("priority_band") == "p2"

    # Supply the field explicitly → the caller's value wins over the default.
    explicit = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="band given", custom_fields={"priority_band": "p1"}),
        admin,
    )
    assert explicit.custom_fields.get("priority_band") == "p1"


async def test_default_value_edit_and_clear_via_patch(db, admin, project):
    field = await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id],
            key="region",
            name="Region",
            type=FieldType.TEXT,
        ),
        actor_id=admin.id,
    )
    updated = await fields_service.update_field(
        db, field.id, FieldDefinitionUpdate(default_value="emea"), actor_id=admin.id
    )
    assert updated.default_value == "emea"

    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="regional"), admin
    )
    assert item.custom_fields.get("region") == "emea"

    # Explicit null clears the default (model_fields_set distinguishes it from omission).
    cleared = await fields_service.update_field(
        db, field.id, FieldDefinitionUpdate(default_value=None), actor_id=admin.id
    )
    assert cleared.default_value is None


# --- issue-mention backlinks ---


async def test_mention_creates_bidirectional_backlink(db, admin, project):
    target = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="the target"), admin
    )
    source = await items_service.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            title="the source",
            description=f"see #[{target.key}]({target.key}) for context",
        ),
        admin,
    )

    # Source shows an outgoing "mentions" edge to the target…
    out = [link for link in source.links.outgoing if link.link_type == ItemLinkType.MENTIONS]
    assert [link.item.key for link in out] == [target.key]

    # …and the target shows the incoming backlink.
    target_read = await items_service.get_item_by_key(db, target.key, admin)
    incoming = [
        link for link in target_read.links.incoming if link.link_type == ItemLinkType.MENTIONS
    ]
    assert [link.item.key for link in incoming] == [source.key]


async def test_mention_links_reconcile_on_edit(db, admin, project):
    a = await items_service.create_item(db, ItemCreate(project_id=project.id, title="A"), admin)
    b = await items_service.create_item(db, ItemCreate(project_id=project.id, title="B"), admin)
    source = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="src", description=f"#[{a.key}]({a.key})"),
        admin,
    )
    assert {link.item.key for link in source.links.outgoing if link.link_type == ItemLinkType.MENTIONS} == {a.key}

    # Rewriting the description to point at B drops the A edge and adds a B edge.
    edited = await items_service.update_item(
        db, source.id, ItemUpdate(description=f"now #[{b.key}]({b.key})"), admin
    )
    assert {link.item.key for link in edited.links.outgoing if link.link_type == ItemLinkType.MENTIONS} == {b.key}


async def test_mention_link_api_rejects_mentions_type(db, admin, project):
    from radd.exceptions import ConflictError
    from radd.modules.items.schemas import ItemLinkCreate

    a = await items_service.create_item(db, ItemCreate(project_id=project.id, title="a"), admin)
    b = await items_service.create_item(db, ItemCreate(project_id=project.id, title="b"), admin)
    with pytest.raises(ConflictError):
        await items_service.add_item_link(
            db, a.id, ItemLinkCreate(target_number=b.number, link_type=ItemLinkType.MENTIONS), admin
        )


# --- timelog hours-per-day: instance-only (spec 67 follow-up) ---


async def test_timelog_hours_per_day_is_instance_only(db, admin, project):
    await enablement.set_enabled(db, project.id, True)
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="timed"), admin
    )

    # The per-project override is retired — a project-scope write 409s.
    with pytest.raises(ConflictError):
        await settings_service.set_value(
            db, SettingKey.TIMELOG_HOURS_PER_DAY, SettingScope.PROJECT, project.id, 6
        )

    # Default is 8h/day → "1d" == 8h. An INSTANCE override of 6 → "1d" == 6h globally.
    await settings_service.set_value(
        db, SettingKey.TIMELOG_HOURS_PER_DAY, SettingScope.INSTANCE, None, 6
    )
    await timelog_service.set_estimate(db, item.id, EstimateSet(estimate="1d"), actor_id=admin.id)
    summary = await timelog_service.item_summary(db, item.id, project)
    assert summary.original_estimate_seconds == 6 * 3600
    # And it formats back through the same factor.
    assert summary.original_estimate == "1d"
