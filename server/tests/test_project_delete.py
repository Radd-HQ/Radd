"""Deleting a project (RADD-1174): complete, refusable, and gated globally.

The invariants worth pinning:

  - the row really goes, and so does everything the database cannot cascade on
    its own — comments (polymorphic parent), scoped settings and subscriptions
    (bare `scope_id`), and the custom fields scoped ONLY to this project, which
    would otherwise be promoted to GLOBAL when their scope rows cascade away;
  - a child moved to another project is detached, not a foreign-key error;
  - a mail source still landing here is a 409 that names it, and the same
    inspection the dialog reads lists it beforehand;
  - the atom is global: `project.manage` on the project is not enough, and
    `global.manage` carries it.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules import workflow  # noqa: F401 — registers the default-state hook
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, Permission, expand_permissions
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake.models import MailSource
from radd.modules.mailintake.types import MailSourceKind
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.projects.types import ProjectEvent
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow.types import TransitionMode


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, label, *, role=InstanceRole.ADMIN) -> User:
    user = User(
        email=f"pd-{label}-{uuid.uuid4().hex[:6]}@example.com",
        name=f"{label.title()} Person",
        instance_role=role.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db, prefix="PD"):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"{prefix}{uuid.uuid4().hex[:4].upper()}", name="Doomed")
    )


async def _count(db, sql: str, **params) -> int:
    return int(await db.scalar(text(sql), params) or 0)


async def test_delete_takes_everything_the_database_cannot_cascade(db):
    admin = await _user(db, "admin")
    project = await _project(db)
    other = await _project(db, "OT")
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="one"), admin)
    await comments_service.create_comment(db, item.id, CommentCreate(body="a comment"), admin)
    await settings_service.set_value(
        db, SettingKey.WORKFLOW_TRANSITION_MODE, SettingScope.PROJECT, project.id,
        TransitionMode.GUARDS.value,
    )
    private = await fields_service.create_field(
        db, FieldDefinitionCreate(project_ids=[project.id], key="pd_private", name="Private", type=FieldType.TEXT)
    )
    shared = await fields_service.create_field(
        db, FieldDefinitionCreate(project_ids=[project.id, other.id], key="pd_shared", name="Shared", type=FieldType.TEXT)
    )
    # A child that was moved to another project keeps pointing at its parent here.
    stray = await items_service.create_item(db, ItemCreate(project_id=other.id, title="moved child"), admin)
    await db.execute(
        text("UPDATE work_items SET parent_id = :p WHERE id = :c"), {"p": item.id, "c": stray.id}
    )

    inspection = await projects_service.inspect_project(db, project)
    assert inspection.counts["items"] == 1
    assert inspection.counts["comments"] == 1
    assert inspection.counts["fields"] == 1  # the private one; the shared one is not ours to take
    assert inspection.counts["views"] >= 1  # the seeded Board/List/…
    assert not inspection.blockers

    removed = await projects_service.delete_project(db, project, actor_id=admin.id)
    assert removed.counts["items"] == 1

    assert await projects_service.project_exists(db, project.id) is False
    assert await _count(db, "SELECT count(*) FROM work_items WHERE project_id = :p", p=project.id) == 0
    assert await _count(db, "SELECT count(*) FROM comments WHERE entity_id = :i", i=item.id) == 0
    assert await _count(db, "SELECT count(*) FROM states WHERE project_id = :p", p=project.id) == 0
    assert await _count(db, "SELECT count(*) FROM views WHERE project_id = :p", p=project.id) == 0
    assert await _count(
        db, "SELECT count(*) FROM scoped_settings WHERE scope = 'project' AND scope_id = :p", p=project.id
    ) == 0
    assert await _count(db, "SELECT count(*) FROM field_definitions WHERE id = :f", f=private.id) == 0
    # The shared field survives, now scoped to the other project alone — never global.
    assert await _count(db, "SELECT count(*) FROM field_definitions WHERE id = :f", f=shared.id) == 1
    assert await _count(
        db, "SELECT count(*) FROM field_definition_projects WHERE field_id = :f", f=shared.id
    ) == 1
    # The stray child is a top-level item now, in its own project, untouched otherwise.
    survivor = await db.get(WorkItem, stray.id)
    await db.refresh(survivor)
    assert survivor.parent_id is None and survivor.project_id == other.id
    # The ledger keeps the deletion, with what went.
    row = (
        await db.execute(
            text("SELECT payload FROM events WHERE event_type = :t AND entity_id = :p"),
            {"t": ProjectEvent.PROJECT_DELETED.value, "p": str(project.id)},
        )
    ).one()
    assert row[0]["key"] == project.key and row[0]["removed"]["items"] == 1


async def test_mail_still_routed_here_blocks_and_is_named(db):
    admin = await _user(db, "admin")
    project = await _project(db)
    db.add(
        MailSource(
            name="Helpdesk", kind=MailSourceKind.WEBHOOK.value, address="help@example.test",
            default_project_id=project.id,
        )
    )
    await db.flush()

    inspection = await projects_service.inspect_project(db, project)
    assert [b.kind for b in inspection.blockers] == ["mail_source"]
    assert "Helpdesk" in inspection.blockers[0].label

    with pytest.raises(ConflictError) as refused:
        await projects_service.delete_project(db, project, actor_id=admin.id)
    assert "Helpdesk" in str(refused.value)
    # Nothing was touched — the refusal came before any destruction.
    assert await projects_service.project_exists(db, project.id)
    assert await _count(db, "SELECT count(*) FROM states WHERE project_id = :p", p=project.id) > 0


def test_the_atom_is_global_and_rides_global_manage():
    """Were `project.delete` project-scoped it would join PROJECT_PERMISSIONS —
    the builtin project Admin role's grant set — and a delegated project admin
    could destroy the project they were handed."""
    from radd.modules.auth.types import PERMISSION_SCOPES, PermissionScope

    assert PERMISSION_SCOPES[Permission.PROJECT_DELETE] is PermissionScope.GLOBAL
    assert Permission.PROJECT_DELETE.value in expand_permissions({Permission.GLOBAL_MANAGE})


async def test_a_member_is_refused_and_an_admin_is_not(db):
    member = await _user(db, "member", role=InstanceRole.MEMBER)
    admin = await _user(db, "admin")
    with pytest.raises(ForbiddenError):
        await authz.require(db, member, Permission.PROJECT_DELETE)
    await authz.require(db, admin, Permission.PROJECT_DELETE)
