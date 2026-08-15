"""Project admins assign roles on their own project (RADD-826 / D3 + D14).

The delegation and its two containment walls: a member.create holder grants
EXISTING roles project-scoped (never wider), and — D14, scope-aware — never a
role carrying atoms they do not hold at that project's scope. Both walls are
server-side; the picker is presentation.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.roles_router import ensure_delegated_role_coverage
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import Permission

# Side effect: workflow's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
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
async def rig(db):
    delegate = User(
        email=f"dg-{uuid.uuid4().hex[:8]}@example.com", name="Delegate", instance_role="member"
    )
    db.add(delegate)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"DG{uuid.uuid4().hex[:4].upper()}", name="D")
    )
    # The delegate's own project role: member admin + item work, NO role.update.
    admin_ish = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}",
            name="Project Admin-ish",
            permissions=[
                Permission.MEMBER_CREATE,
                Permission.MEMBER_UPDATE,
                Permission.MEMBER_DELETE,
                Permission.ITEM_READ,
                Permission.ITEM_UPDATE,
            ],
        ),
    )
    db.add(GlobalRoleGrant(project_id=project.id, user_id=delegate.id, role_id=admin_ish.id))
    await db.flush()
    return delegate, project


async def test_delegate_may_hand_out_what_they_hold_at_this_scope(db, rig):
    """D14's scope-aware clause: the delegate holds item.update on THE PROJECT
    only (not globally) — and that is enough, or delegation mostly refuses."""
    delegate, project = rig
    editor = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}",
            name="Editor",
            permissions=[Permission.ITEM_READ, Permission.ITEM_UPDATE],
        ),
    )
    await ensure_delegated_role_coverage(db, delegate, editor, project)  # no raise


async def test_delegate_cannot_hand_out_atoms_they_lack(db, rig):
    delegate, project = rig
    wide = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}",
            name="Wide",
            permissions=[Permission.PROJECT_MANAGE],  # expands far past the delegate
        ),
    )
    with pytest.raises(ForbiddenError):
        await ensure_delegated_role_coverage(db, delegate, wide, project)


async def test_relation_qualified_roles_compare_by_the_lattice(db, rig):
    """Holding item.update (@any) covers granting item.update@own — a delegate
    can hand out LESS than they hold, never more."""
    delegate, project = rig
    narrow = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}",
            name="Own-only",
            permissions=[Permission.ITEM_READ, "item.update@own"],
        ),
    )
    await ensure_delegated_role_coverage(db, delegate, narrow, project)  # no raise
    # The inverse direction refuses: an @any-granting role vs an @own holder.
    holder = User(
        email=f"dg-{uuid.uuid4().hex[:8]}@example.com", name="Own holder", instance_role="member"
    )
    db.add(holder)
    await db.flush()
    own_role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}",
            name="Own admin",
            permissions=[Permission.MEMBER_CREATE, "item.update@own"],
        ),
    )
    db.add(GlobalRoleGrant(project_id=project.id, user_id=holder.id, role_id=own_role.id))
    await db.flush()
    any_role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}", name="Any", permissions=[Permission.ITEM_UPDATE]
        ),
    )
    with pytest.raises(ForbiddenError):
        await ensure_delegated_role_coverage(db, holder, any_role, project)


async def test_member_update_changes_a_grant_role_in_place(db, rig):
    """RADD-1103: member.update's first enforcement site. A project delegate
    holding it swaps WHICH role a project-scoped grant confers — one row, one
    event — but only into roles their own coverage allows, and never on a
    global grant."""
    from radd.modules.auth.roles_router import update_role_grant
    from radd.modules.auth.schemas import RoleGrantRoleUpdate

    delegate, project = rig
    reader = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}", name="Reader",
            permissions=[Permission.ITEM_READ],
        ),
    )
    editor = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}", name="Editor2",
            permissions=[Permission.ITEM_READ, Permission.ITEM_UPDATE],
        ),
    )
    subject = User(
        email=f"su-{uuid.uuid4().hex[:8]}@example.com", name="Subject", instance_role="member"
    )
    db.add(subject)
    await db.flush()
    grant = GlobalRoleGrant(project_id=project.id, user_id=subject.id, role_id=reader.id)
    db.add(grant)
    await db.flush()

    updated = await update_role_grant(
        grant.id, RoleGrantRoleUpdate(role_id=editor.id), db, delegate
    )
    assert updated.role_id == editor.id

    # coverage wall: a role carrying atoms the delegate lacks refuses
    admin_role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"dg{uuid.uuid4().hex[:6]}", name="Wider",
            permissions=[Permission.ITEM_READ, Permission.ROLE_UPDATE],
        ),
    )
    with pytest.raises(ForbiddenError):
        await update_role_grant(grant.id, RoleGrantRoleUpdate(role_id=admin_role.id), db, delegate)

    # a GLOBAL grant is beyond member.update — needs role.update
    global_grant = GlobalRoleGrant(project_id=None, user_id=subject.id, role_id=reader.id)
    db.add(global_grant)
    await db.flush()
    with pytest.raises(ForbiddenError):
        await update_role_grant(
            global_grant.id, RoleGrantRoleUpdate(role_id=editor.id), db, delegate
        )
