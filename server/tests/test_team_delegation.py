"""Team ownership, delegated management, and the stale-group guard (spec 87).

The invariants worth pinning:
  - a team leader administers THEIR team and no other (that is the whole point
    of per-team delegation over the all-or-nothing team.update atom),
  - a delegate cannot promote themselves — appointing managers and transferring
    ownership stay with the owner,
  - a directory group that vanishes from AD never empties the team it is linked to.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.ldap import groups, groupsync
from radd.modules.ldap.types import DirectoryGroup, DirectoryUnreachable

# Imported for its side effect: the workflow module registers the in-txn
# `project.created` hook that seeds a project's default states, and the item
# fixtures below need one to land in.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.teams import service as teams_service
from radd.modules.teams.models import TeamMember
from radd.modules.teams.schemas import TeamCreate, TeamUpdate
from radd.modules.teams.types import MemberSource, TeamSource


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name, *, instance_role=InstanceRole.MEMBER, active=True) -> User:
    user = User(
        email=f"td-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=instance_role.value,
        active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _team(db, owner) -> object:
    return await teams_service.create_team(
        db, TeamCreate(name=f"TD-{uuid.uuid4().hex[:6]}"), actor_id=owner.id
    )


async def test_stewardship_is_per_team(db):
    """A manager of one team is nobody on another — the property that makes this
    delegation rather than a global grant."""
    owner = await _user(db, "Owner")
    lead = await _user(db, "Team lead")
    outsider = await _user(db, "Outsider")
    mine = await _team(db, owner)
    theirs = await _team(db, owner)

    assert await teams_service.is_team_steward(db, owner.id, mine)  # creator owns it
    assert not await teams_service.is_team_steward(db, lead.id, mine)

    await teams_service.replace_managers(db, mine.id, [lead.id], actor_id=owner.id)
    assert await teams_service.is_team_steward(db, lead.id, mine)
    assert not await teams_service.is_team_steward(db, lead.id, theirs)
    assert not await teams_service.is_team_steward(db, outsider.id, mine)

    # A manager need not be a member — a lead can run a team they are not on.
    assert lead.id not in [u.id for u in await teams_service.list_team_members(db, mine.id)]

    # Full-state replace: dropping the lead revokes stewardship.
    await teams_service.replace_managers(db, mine.id, [], actor_id=owner.id)
    assert not await teams_service.is_team_steward(db, lead.id, mine)


async def test_transfer_keeps_previous_owner_as_manager_and_refuses_inactive(db):
    owner = await _user(db, "Owner")
    successor = await _user(db, "Successor")
    retired = await _user(db, "Retired", active=False)
    team = await _team(db, owner)

    with pytest.raises(ConflictError):
        await teams_service.transfer_ownership(db, team.id, retired.id, actor_id=owner.id)

    await teams_service.transfer_ownership(db, team.id, successor.id, actor_id=owner.id)
    assert team.owner_id == successor.id
    # No accidental lockout: the previous owner stays on as a manager.
    assert owner.id in await teams_service.list_managers(db, team.id)
    # …and the new owner's now-redundant manager row is gone (ownership subsumes it).
    assert successor.id not in await teams_service.list_managers(db, team.id)


async def test_delete_refuses_while_the_team_grants_project_access(db):
    from radd.modules.auth import roles as auth_roles
    from radd.modules.auth.types import BuiltinRoleKey
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate
    from radd.modules.teams.schemas import ProjectTeamAttach

    owner = await _user(db, "Owner", instance_role=InstanceRole.ADMIN)
    team = await _team(db, owner)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"TD{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    # No app boot in these tests — ensure the startup-seeded builtin roles exist.
    await auth_roles.ensure_builtin_roles(db)
    role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    await teams_service.attach_project_team(
        db, project.id, ProjectTeamAttach(team_id=team.id, role_id=role.id), actor_id=owner.id
    )

    with pytest.raises(ConflictError):  # would silently revoke everyone's access
        await teams_service.delete_team(db, team.id, actor_id=owner.id)

    await teams_service.detach_project_team(db, project.id, team.id, actor_id=owner.id)

    # Items naming the team block it too — work_items.team_id is RESTRICT, so
    # without the guard this would surface as a 500 instead of an answer.
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="assigned"), owner
    )
    await items_service.update_item(db, item.id, ItemUpdate(team_id=team.id), owner)
    with pytest.raises(ConflictError):
        await teams_service.delete_team(db, team.id, actor_id=owner.id)

    await items_service.update_item(db, item.id, ItemUpdate(team_id=None), owner)
    await teams_service.delete_team(db, team.id, actor_id=owner.id)


async def test_directory_team_membership_is_read_only(db):
    owner = await _user(db, "Owner")
    member = await _user(db, "Member")
    team = await _team(db, owner)
    await teams_service.update_team(
        db,
        team.id,
        TeamUpdate(
            directory_group_dn="CN=g,OU=Groups,DC=ad,DC=example,DC=com", directory_group_name="g"
        ),
        actor_id=owner.id,
    )
    assert TeamSource(team.source) is TeamSource.DIRECTORY

    with pytest.raises(ConflictError):
        await teams_service.add_team_member(db, team.id, member.id, actor_id=owner.id)
    # Even the owner cannot hand-edit it — the directory is the single source.
    db.add(TeamMember(team_id=team.id, user_id=member.id, source=MemberSource.DIRECTORY))
    await db.flush()
    with pytest.raises(ConflictError):
        await teams_service.remove_team_member(db, team.id, member.id, actor_id=owner.id)


async def test_vanished_ad_group_never_empties_the_team(db, monkeypatch):
    owner = await _user(db, "Owner", instance_role=InstanceRole.ADMIN)
    member = await _user(db, "Synced")
    group_dn = "CN=gone,OU=Groups,DC=ad,DC=example,DC=com"
    team = await _team(db, owner)
    await teams_service.update_team(
        db, team.id, TeamUpdate(directory_group_dn=group_dn, directory_group_name="gone")
    )
    db.add(TeamMember(team_id=team.id, user_id=member.id, source=MemberSource.DIRECTORY))
    await db.flush()

    async def no_members(session, dn):
        return []

    async def group_gone(dn):
        return None

    monkeypatch.setattr(groups, "search_group_members", no_members)
    monkeypatch.setattr(groups, "get_group", group_gone)

    # An empty search + a group that no longer resolves must NOT read as "everyone left".
    with pytest.raises(groupsync.StaleDirectoryGroup):
        await groupsync.reconcile_team(db, team, actor_id=owner.id)
    rows = await teams_service.team_member_rows(db, team.id)
    assert [r.user_id for r in rows] == [member.id]
    assert team.directory_missing_since is not None

    # While flagged, the login path holds removals too (it would otherwise drain
    # the team one sign-in at a time).
    await groupsync.sync_login_membership(db, member, [team], frozenset())
    assert len(await teams_service.team_member_rows(db, team.id)) == 1

    # A genuinely empty group that still EXISTS does reconcile, and clears the flag.
    async def group_exists(dn):
        return DirectoryGroup(cn="gone", dn=dn, description="", member_count=0)

    monkeypatch.setattr(groups, "get_group", group_exists)
    added, removed = await groupsync.reconcile_team(db, team, actor_id=owner.id)
    assert (added, removed) == (0, 1)
    assert team.directory_missing_since is None
    assert await teams_service.team_member_rows(db, team.id) == []


async def test_unreachable_directory_is_not_a_missing_group(db, monkeypatch):
    """The distinction the whole guard rests on: a DC that can't be reached must
    never be read as "the group is gone", which would flag a healthy team and
    tell the admin their AD is wrong when it isn't."""
    owner = await _user(db, "Owner", instance_role=InstanceRole.ADMIN)
    team = await _team(db, owner)
    await teams_service.update_team(
        db,
        team.id,
        TeamUpdate(
            directory_group_dn="CN=fine,OU=Groups,DC=ad,DC=example,DC=com",
            directory_group_name="fine",
        ),
    )

    async def no_members(session, dn):
        return []

    async def dc_down(dn):
        raise DirectoryUnreachable("connection refused")

    monkeypatch.setattr(groups, "search_group_members", no_members)
    monkeypatch.setattr(groups, "get_group", dc_down)

    with pytest.raises(DirectoryUnreachable):
        await groupsync.reconcile_team(db, team, actor_id=owner.id)
    assert team.directory_missing_since is None  # NOT flagged as stale


async def test_unknown_manager_is_refused(db):
    owner = await _user(db, "Owner")
    team = await _team(db, owner)
    with pytest.raises(ConflictError):
        await teams_service.replace_managers(db, team.id, [uuid.uuid4()], actor_id=owner.id)
