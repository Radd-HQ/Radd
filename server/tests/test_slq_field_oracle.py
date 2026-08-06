"""RADD-840 — the SLQ compiler is part of the access surface, and search
stops indexing read-restricted description text.

Filtering/sorting on a field the actor can't read disclosed its value by
bisection (`/items/count` made the oracle cheap); the compiler now refuses at
compile time. `description` is read-restrictable AND searchable; the indexer
now blanks it conservatively (for nobody) wherever a read-restriction covers
the project. Every assertion failed on the pre-fix code.

DB-backed; flushed, never committed.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.access import service as access_service
from radd.modules.access.types import GrantSubject
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import ProjectMember, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import BuiltinItemField, FieldAccess, FieldType
from radd.modules.items import bulk, service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.slq import SlqError
from radd.modules.search import indexer
from radd.modules.search.models import SearchIndexRow
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"orc-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"OR{uuid.uuid4().hex[:4].upper()}", name="P")
    )


@pytest.fixture
async def member(db, project) -> User:
    user = User(
        email=f"orc-m-{uuid.uuid4().hex[:8]}@example.com",
        name="Member",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role_id=role.id))
    await db.flush()
    return user


async def _restricting_role(db) -> uuid.UUID:
    role = await auth_roles.create_role(
        db, RoleCreate(key=f"orl{uuid.uuid4().hex[:6]}", name="Locked")
    )
    return role.id


async def _restrict_custom_read(db, definition):
    await access_service.add_grant(
        db,
        "field",
        str(definition.id),
        subject_type=GrantSubject.ROLE,
        subject_id=await _restricting_role(db),
        access=FieldAccess.READ.value,
    )


async def _restrict_builtin_read(db, field: str, project_id=None):
    return await access_service.add_grant(
        db,
        fields_service.BUILTIN_RESOURCE,
        field,
        subject_type=GrantSubject.ROLE,
        subject_id=await _restricting_role(db),
        access=FieldAccess.READ.value,
        project_id=project_id,
    )


# --- the compiler refuses filters/sorts on read-restricted fields ---------------


async def test_restricted_custom_field_refuses_filter_and_sort(db, admin, project, member):
    definition = await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id], key="salary", name="Salary", type=FieldType.NUMBER
        ),
    )
    await items.create_item(
        db, ItemCreate(project_id=project.id, title="i", custom_fields={"salary": 90}), admin
    )
    await _restrict_custom_read(db, definition)
    filters = ItemListFilters(project_id=project.id)

    with pytest.raises(SlqError):
        await items.list_items(
            db, actor=member, filters=filters, q="salary > 50", limit=10, offset=0
        )
    with pytest.raises(SlqError):
        await bulk.count_items(db, actor=member, filters=filters, q="salary > 50")
    with pytest.raises(SlqError):
        await items.list_items(
            db, actor=member, filters=filters, q="ORDER BY salary", limit=10, offset=0
        )
    # The admin (manage) still filters by it.
    rows = await items.list_items(
        db, actor=admin, filters=filters, q="salary > 50", limit=10, offset=0
    )
    assert len(rows) == 1


async def test_restricted_builtin_refuses_filter_project_and_cross(db, admin, project, member):
    await items.create_item(
        db, ItemCreate(project_id=project.id, title="i", assignee_id=admin.id), admin
    )
    await _restrict_builtin_read(db, BuiltinItemField.ASSIGNEE.value)

    with pytest.raises(SlqError):
        await items.list_items(
            db,
            actor=member,
            filters=ItemListFilters(project_id=project.id),
            q="assignee IS NOT EMPTY",
            limit=10,
            offset=0,
        )
    # Cross-project (no project scope): conservative denial for non-admins.
    with pytest.raises(SlqError):
        await bulk.count_items(
            db, actor=member, filters=ItemListFilters(), q="assignee IS NOT EMPTY"
        )
    # The ancestor mirror is the same oracle.
    with pytest.raises(SlqError):
        await bulk.count_items(
            db,
            actor=member,
            filters=ItemListFilters(project_id=project.id),
            q="epic.assignee = none",
        )


async def test_restricted_points_refuses_and_admin_passes(db, admin, project, member):
    await items.create_item(
        db, ItemCreate(project_id=project.id, title="i", estimate_points=8), admin
    )
    await _restrict_builtin_read(db, "estimate_points")
    with pytest.raises(SlqError):
        await bulk.count_items(
            db, actor=member, filters=ItemListFilters(project_id=project.id), q="points > 3"
        )
    count = await bulk.count_items(
        db, actor=admin, filters=ItemListFilters(project_id=project.id), q="points > 3"
    )
    assert count == 1


# --- the index blanks restricted description text -------------------------------


def _item_event(item, project, description):
    return SimpleNamespace(
        entity_id=str(item.id),
        payload={
            "item": {
                "id": str(item.id),
                "project": {"id": str(project.id), "key": project.key, "name": project.name},
                "key": item.key,
                "title": item.title,
                "description": description,
            }
        },
    )


async def test_index_blanks_restricted_description(db, admin, project):
    secret = "the secret launch codes"
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="classified", description=secret), admin
    )
    await indexer._index_item(db, _item_event(item, project, secret))
    row = await db.get(SearchIndexRow, item.id)
    assert row is not None and row.description == secret

    grant = await _restrict_builtin_read(
        db, BuiltinItemField.DESCRIPTION.value, project_id=project.id
    )
    await indexer.sync_description_restriction(db)
    await db.refresh(row)
    assert row.description == ""

    # New indexing while restricted stays blank.
    await indexer._index_item(db, _item_event(item, project, secret))
    await db.refresh(row)
    assert row.description == ""

    # Revoking the grant restores the text from work_items.
    await access_service.remove_grant(db, grant.id)
    await indexer.sync_description_restriction(db)
    await db.refresh(row)
    assert row.description == secret
