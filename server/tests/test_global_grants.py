"""Instance-wide role grants (spec 87): a custom role holding a global atom (e.g.
`label.create`) must deliver it — to a user directly and via their teams — where
the old `instance_role`-only check granted nothing; and a global grant applies on
every project, so project-scoped atoms inside it are live too.
"""

import uuid

import pytest

from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import authz, grants, roles as roles_service
from radd.modules.auth.schemas import GlobalGrantEntry, RoleCreate
from radd.modules.auth.types import Permission
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

from _factories import make_user


async def _role(db, *permissions):
    return await roles_service.create_role(
        db,
        RoleCreate(
            key=f"gg-{uuid.uuid4().hex[:8]}",
            name="Label wrangler",
            permissions=list(permissions),
        ),
    )


async def test_global_grant_delivers_a_global_atom(db):
    """A plain member holds no global atom; granted the role instance-wide, they do."""
    user = await make_user(db, name="Wrangler")
    role = await _role(db, Permission.LABEL_CREATE)

    assert Permission.LABEL_CREATE not in await authz.effective_permissions(db, user)
    with pytest.raises(ForbiddenError):
        await authz.require(db, user, Permission.LABEL_CREATE)

    await grants.replace_grants(db, role.id, [GlobalGrantEntry(user_id=user.id)])

    permissions = await authz.effective_permissions(db, user)
    assert Permission.LABEL_CREATE in permissions
    await authz.require(db, user, Permission.LABEL_CREATE)  # no raise
    # The floor survives alongside the grant — item.read@OWN since RADD-825.
    assert "item.read@own" in permissions


async def test_global_grant_via_team_and_umbrella_expansion(db):
    """Grants resolve through team membership, and umbrellas still expand:
    global.manage must yield team.create/update/delete at global scope
    (RADD-816 deleted the dead team.manage umbrella)."""
    user = await make_user(db, name="Team-granted")
    team = await teams_service.create_team(db, TeamCreate(name=f"GG-{uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, user.id)
    role = await _role(db, Permission.GLOBAL_MANAGE)

    await grants.replace_grants(db, role.id, [GlobalGrantEntry(team_id=team.id)])

    permissions = await authz.effective_permissions(db, user)
    assert {Permission.TEAM_CREATE, Permission.TEAM_UPDATE, Permission.TEAM_DELETE} <= permissions


async def test_global_grant_applies_inside_every_project(db):
    """The reach decision: a globally-granted role is unioned in at project
    scope too, so its project-scoped atoms are not a new dead grant."""
    user = await make_user(db, name="Global editor")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"GG{uuid.uuid4().hex[:6].upper()}", name="Grant reach")
    )
    role = await _role(db, Permission.ITEM_CREATE)

    # No project membership: the floor is read-only.
    assert Permission.ITEM_CREATE not in await authz.effective_permissions(db, user, project=project)

    await grants.replace_grants(db, role.id, [GlobalGrantEntry(user_id=user.id)])

    assert Permission.ITEM_CREATE in await authz.effective_permissions(db, user, project=project)
    # …and through the batched path the list hydration uses.
    batched = await authz.permissions_for_projects(db, user, [project])
    assert Permission.ITEM_CREATE in batched[project.id]


async def test_project_scoped_grant_applies_only_on_that_project(db):
    """Spec 91: a grant scoped to project A delivers the role's project atoms on A,
    but NOT on another project and NOT at global scope."""
    user = await make_user(db, name="Scoped editor")
    a = await projects_service.create_project(
        db, ProjectCreate(key=f"GA{uuid.uuid4().hex[:6].upper()}", name="Alpha")
    )
    b = await projects_service.create_project(
        db, ProjectCreate(key=f"GB{uuid.uuid4().hex[:6].upper()}", name="Beta")
    )
    role = await _role(db, Permission.ITEM_CREATE)

    await grants.create_grant(db, role.id, user_id=user.id, project_id=a.id)

    assert Permission.ITEM_CREATE in await authz.effective_permissions(db, user, project=a)
    assert Permission.ITEM_CREATE not in await authz.effective_permissions(db, user, project=b)
    # Global scope never sees a project-scoped grant.
    assert Permission.ITEM_CREATE not in await authz.effective_permissions(db, user)
    # Batched path agrees: A yes, B no.
    batched = await authz.permissions_for_projects(db, user, [a, b])
    assert Permission.ITEM_CREATE in batched[a.id]
    assert Permission.ITEM_CREATE not in batched[b.id]


async def test_grant_centric_create_and_delete_and_dup_guard(db):
    user = await make_user(db, name="Grantee")
    role = await _role(db, Permission.LABEL_CREATE)

    grant = await grants.create_grant(db, role.id, user_id=user.id)  # global
    assert Permission.LABEL_CREATE in await authz.effective_permissions(db, user)
    # Duplicate global grant is rejected.
    with pytest.raises(ConflictError):
        await grants.create_grant(db, role.id, user_id=user.id)

    await grants.delete_grant(db, grant.id)
    assert Permission.LABEL_CREATE not in await authz.effective_permissions(db, user)


async def test_grants_for_subject_lists_all_scopes(db):
    user = await make_user(db, name="Multi")
    a = await projects_service.create_project(
        db, ProjectCreate(key=f"GS{uuid.uuid4().hex[:6].upper()}", name="Alpha")
    )
    role = await _role(db, Permission.ITEM_CREATE)
    await grants.create_grant(db, role.id, user_id=user.id)  # global
    await grants.create_grant(db, role.id, user_id=user.id, project_id=a.id)  # project
    rows = await grants.grants_for_subject(db, user_id=user.id)
    assert len(rows) == 2
    assert {r.project_id for r in rows} == {None, a.id}
    # The role's Roles-page editor sees only the GLOBAL grant.
    assert {g.project_id for g in await grants.list_grants(db, role.id)} == {None}


async def test_replace_is_full_state_and_guards_its_subjects(db):
    user = await make_user(db, name="Holder")
    other = await make_user(db, name="Replacement")
    role = await _role(db, Permission.LABEL_CREATE)

    await grants.replace_grants(db, role.id, [GlobalGrantEntry(user_id=user.id)])
    await grants.replace_grants(db, role.id, [GlobalGrantEntry(user_id=other.id)])

    # Replaced, not appended — the first holder lost the atom.
    assert Permission.LABEL_CREATE not in await authz.effective_permissions(db, user)
    assert Permission.LABEL_CREATE in await authz.effective_permissions(db, other)

    with pytest.raises(ConflictError):  # duplicate subject
        await grants.replace_grants(
            db, role.id, [GlobalGrantEntry(user_id=other.id), GlobalGrantEntry(user_id=other.id)]
        )
    with pytest.raises(ConflictError):  # unknown subject
        await grants.replace_grants(db, role.id, [GlobalGrantEntry(user_id=uuid.uuid4())])


async def test_granted_role_blocks_deletion_and_inactive_users_hold_nothing(db):
    user = await make_user(db, name="Holder")
    role = await _role(db, Permission.LABEL_CREATE)
    await grants.replace_grants(db, role.id, [GlobalGrantEntry(user_id=user.id)])

    with pytest.raises(ConflictError):
        await roles_service.delete_role(db, role.id)

    user.active = False
    await db.flush()
    assert await authz.effective_permissions(db, user) == frozenset()
