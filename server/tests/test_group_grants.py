"""Groups as grant subjects (RADD-832).

The ask this pins: "grants to AD groups directly, not just through teams."
A role granted to a GROUP reaches every transitive member (nesting resolved by
the RADD-830 closure, never flattened at grant time); the spec-92 access
framework accepts GROUP subjects on every registered resource; and both
enforcement paths — atom resolution and share/grant matching — read the same
closure, so a parent-group grant reaches a nested child's members without
either side knowing the graph's shape.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.access import resolution, service as access_service
from radd.modules.access.registry import ResourceSpec
from radd.modules.access.types import GrantSubject
from radd.modules.auth import authz, grants as role_grants, roles as auth_roles
from radd.modules.auth.models import ProjectMember, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, Permission
from radd.modules.groups import service as groups_service
from radd.modules.groups.models import GroupMember

# Side effect: the workflow module's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.views import service as views_service
from radd.modules.views.schemas import ViewCreate, ViewShareEntry
from radd.modules.views.types import ViewType


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name) -> User:
    user = User(
        email=f"gg-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role="member"
    )
    db.add(user)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    return user


async def _nested_pair(db, member: User):
    """parent ⊃ child, with `member` a DIRECT member of the CHILD only."""
    suffix = uuid.uuid4().hex[:6]
    parent = await groups_service.upsert_group(db, dn=f"CN=p{suffix},DC=t", name=f"P{suffix}")
    child = await groups_service.upsert_group(db, dn=f"CN=c{suffix},DC=t", name=f"C{suffix}")
    await groups_service.set_parents(db, child, [parent.id])
    db.add(GroupMember(group_id=child.id, user_id=member.id))
    await db.flush()
    groups_service.forget_user_groups(db)
    return parent, child


# --- the role-grant table ------------------------------------------------------


async def test_role_granted_to_parent_group_reaches_nested_member(db):
    """The headline Done-when: an admin grants a role to an AD group directly —
    no team involved — and a member of a NESTED child group holds its atoms."""
    member = await _user(db, "Nested Member")
    outsider = await _user(db, "Outsider")
    parent, _child = await _nested_pair(db, member)
    role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"gg{uuid.uuid4().hex[:6]}", name="G", permissions=[Permission.LABEL_CREATE]
        ),
    )
    await role_grants.create_grant(db, role.id, group_id=parent.id)

    assert Permission.LABEL_CREATE in await authz.effective_permissions(db, member)
    assert Permission.LABEL_CREATE not in await authz.effective_permissions(db, outsider)


async def test_group_grant_scoped_to_a_project_stays_scoped(db):
    member = await _user(db, "Scoped")
    parent, _child = await _nested_pair(db, member)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"GG{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"gg{uuid.uuid4().hex[:6]}", name="G", permissions=[Permission.ITEM_UPDATE]
        ),
    )
    await role_grants.create_grant(db, role.id, group_id=parent.id, project_id=project.id)

    on_project = await authz.effective_permissions(db, member, project=project)
    assert Permission.ITEM_UPDATE in on_project
    assert Permission.ITEM_UPDATE not in await authz.effective_permissions(db, member)


async def test_group_held_roles_reach_the_inspector_subject_set(db):
    member = await _user(db, "Inspected")
    parent, _child = await _nested_pair(db, member)
    role = await auth_roles.create_role(
        db, RoleCreate(key=f"gg{uuid.uuid4().hex[:6]}", name="G", permissions=[])
    )
    await role_grants.create_grant(db, role.id, group_id=parent.id)
    assert role.id in await authz.all_held_role_ids(db, member)


async def test_role_grant_subject_is_exactly_one_of_three(db):
    member = await _user(db, "Two Subjects")
    parent, _ = await _nested_pair(db, member)
    role = await auth_roles.create_role(
        db, RoleCreate(key=f"gg{uuid.uuid4().hex[:6]}", name="G", permissions=[])
    )
    with pytest.raises(ConflictError):
        await role_grants.create_grant(db, role.id, user_id=member.id, group_id=parent.id)
    with pytest.raises(ConflictError):
        await role_grants.create_grant(db, role.id)
    with pytest.raises(ConflictError):
        await role_grants.create_grant(db, role.id, group_id=uuid.uuid4())


# --- the access-grant table ----------------------------------------------------


def test_subject_matches_resolves_a_group_grant_through_the_closure():
    """Pure resolution: the ctx carries the TRANSITIVE closure, so a grant on a
    parent group matches a nested member whose ctx includes the ancestor."""

    class _G:
        subject_type = GrantSubject.GROUP.value
        subject_id = uuid.uuid4()
        access = "read"
        project_id = None

    grant = _G()
    inside = resolution.SubjectContext(
        user_id=uuid.uuid4(), group_ids=frozenset({grant.subject_id})
    )
    outside = resolution.SubjectContext(user_id=uuid.uuid4(), group_ids=frozenset())
    assert resolution.subject_matches(grant, inside)
    assert not resolution.subject_matches(grant, outside)


async def test_access_grant_validates_the_group_exists(db):
    member = await _user(db, "Validator")
    with pytest.raises(ConflictError):
        await access_service.add_grant(
            db,
            "view",
            str(uuid.uuid4()),
            subject_type=GrantSubject.GROUP,
            subject_id=uuid.uuid4(),
            access="viewer",
        )
    assert member is not None  # the fixture seeded builtin roles for the specs


async def test_view_shared_with_parent_group_is_visible_to_nested_member(db):
    """The spec-92 surface end to end: a view shared with a PARENT group appears
    in a nested child member's list and stays invisible to an outsider — the
    share enforcement (`_grant_level`) reads the same closure as authz."""
    owner = await _user(db, "Owner")
    member = await _user(db, "Reader")
    outsider = await _user(db, "Stranger")
    # Everyone passes the member floor (item.read somewhere), so the visibility
    # difference below is the SHARE and nothing else.
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"GV{uuid.uuid4().hex[:4].upper()}", name="V")
    )
    member_role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    for actor in (owner, member, outsider):
        db.add(ProjectMember(project_id=project.id, user_id=actor.id, role_id=member_role.id))
    await db.flush()
    parent, _child = await _nested_pair(db, member)
    view = await views_service.create_view(
        db,
        ViewCreate(
            name=f"Grouped {uuid.uuid4().hex[:6]}",
            view_type=ViewType.LIST.value,
            shares=[ViewShareEntry(group_id=parent.id)],
        ),
        actor=owner,
    )

    member_views = {v.id for v in await views_service.list_views(db, actor=member, project_id=None)}
    outsider_views = {
        v.id for v in await views_service.list_views(db, actor=outsider, project_id=None)
    }
    assert view.id in member_views
    assert view.id not in outsider_views
    # The share row names the group, so the sharing editor can render it.
    hydrated = next(v for v in await views_service.list_views(db, actor=owner, project_id=None) if v.id == view.id)
    assert any(s.group is not None and s.group.id == parent.id for s in hydrated.shares)


def test_every_default_spec_offers_the_group_subject():
    """The registry default carries GROUP, so a resource that never overrode
    `subjects` (custom fields, builtin fields) offers groups with no edit."""
    spec = ResourceSpec(resource_type="x", can_manage=None)  # type: ignore[arg-type]
    assert GrantSubject.GROUP in spec.subjects


async def test_inspector_shows_the_nesting_chain(db):
    """RADD-833: access through a three-level chain reads as the PATH — the
    granted group, then each hop down to the user's direct membership."""
    member = await _user(db, "Chained")
    suffix = uuid.uuid4().hex[:6]
    studio = await groups_service.upsert_group(db, dn=f"CN=st{suffix},DC=t", name="Studio")
    vfx = await groups_service.upsert_group(db, dn=f"CN=vf{suffix},DC=t", name="VFX All")
    wranglers = await groups_service.upsert_group(
        db, dn=f"CN=wr{suffix},DC=t", name="Render Wranglers"
    )
    await groups_service.set_parents(db, vfx, [studio.id])
    await groups_service.set_parents(db, wranglers, [vfx.id])
    db.add(GroupMember(group_id=wranglers.id, user_id=member.id))
    await db.flush()
    groups_service.forget_user_groups(db)
    role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"gg{uuid.uuid4().hex[:6]}", name="G", permissions=[Permission.LABEL_CREATE]
        ),
    )
    # Granted on STUDIO — the group the member has never heard of.
    await role_grants.create_grant(db, role.id, group_id=studio.id)

    sources = await authz.permission_sources(db, member)
    row = next(s for s in sources if s.permission == Permission.LABEL_CREATE.value)
    assert row.via == "group"
    assert row.via_group == "Studio"
    assert row.group_path == ["Studio", "VFX All", "Render Wranglers"]


async def test_expired_grant_stops_applying_at_resolution(db):
    """RADD-820: expiry applies THE MOMENT it passes — resolution, not the
    sweep, is what makes a temporary elevation actually temporary."""
    from datetime import UTC, datetime, timedelta

    member = await _user(db, "Temporary")
    role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"gg{uuid.uuid4().hex[:6]}", name="G", permissions=[Permission.LABEL_CREATE]
        ),
    )
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    future = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
    grant = await role_grants.create_grant(
        db, role.id, user_id=member.id, expires_at=future, actor_id=member.id
    )
    assert grant.granted_by == member.id  # who decided, on the row
    assert Permission.LABEL_CREATE in await authz.effective_permissions(db, member)
    grant.expires_at = past
    await db.flush()
    assert Permission.LABEL_CREATE not in await authz.effective_permissions(db, member)
