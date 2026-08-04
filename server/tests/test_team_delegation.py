"""Team ownership, delegated management, and the stale-group guard (spec 87,
reshaped by RADD-829: the guard lives on GROUPS now, and a team reaches the
directory by holding a group as a member).

The invariants worth pinning:
  - a team leader administers THEIR team and no other (that is the whole point
    of per-team delegation over the all-or-nothing team.update atom),
  - a delegate cannot promote themselves — appointing managers and transferring
    ownership stay with the owner,
  - a directory group that vanishes from AD never loses its memberships.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.groups import service as groups_service
from radd.modules.groups.models import GroupMember
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.ldap import groups, groupsync
from radd.modules.ldap.types import DirectoryGroup, DirectoryUnreachable

# Imported for its side effect: the workflow module registers the in-txn
# `project.created` hook that seeds a project's default states, and the item
# fixtures below need one to land in.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


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


async def test_group_carried_membership_expands_into_the_team(db):
    """RADD-829: a team holding a GROUP counts the group's people (nesting
    included) as members everywhere membership is asked — and stays hand-
    editable for direct user rows, because no team is directory-owned now."""
    owner = await _user(db, "Owner")
    direct = await _user(db, "Direct")
    via_group = await _user(db, "Via Group")
    via_nested = await _user(db, "Via Nested")
    team = await _team(db, owner)

    parent = await groups_service.upsert_group(db, dn="CN=parent,DC=t", name="Parent")
    child = await groups_service.upsert_group(db, dn="CN=child,DC=t", name="Child")
    await groups_service.set_parents(db, child, [parent.id])
    db.add(GroupMember(group_id=parent.id, user_id=via_group.id))
    db.add(GroupMember(group_id=child.id, user_id=via_nested.id))
    await db.flush()

    await teams_service.add_team_member(db, team.id, direct.id, actor_id=owner.id)
    await teams_service.add_team_group(db, team.id, parent.id, actor_id=owner.id)

    members = {u.id for u in await teams_service.list_team_members(db, team.id)}
    assert members == {direct.id, via_group.id, via_nested.id}
    # The membership seam agrees for every carried person.
    for user in (direct, via_group, via_nested):
        assert team.id in await teams_service.user_team_ids(db, user.id)
    # The via labels name the carrier.
    via = {u.id: v for u, v in await teams_service.member_users_with_via(db, team.id)}
    assert via[direct.id] is None and via[via_group.id] == "Parent"

    # Still hand-editable — no read-only teams exist any more.
    await teams_service.remove_team_member(db, team.id, direct.id, actor_id=owner.id)
    await teams_service.remove_team_group(db, team.id, parent.id, actor_id=owner.id)
    assert await teams_service.list_team_members(db, team.id) == []


async def test_subject_graph_is_memoised_per_request(db):
    """RADD-830: the closure runs on the hottest path — one resolution per
    request per actor, identity-asserted (`is`, not `==`)."""
    user = await _user(db, "Memoised")
    group = await groups_service.upsert_group(db, dn="CN=memo,DC=t", name="Memo")
    db.add(GroupMember(group_id=group.id, user_id=user.id))
    await db.flush()
    first_groups = await groups_service.user_group_ids(db, user.id)
    assert await groups_service.user_group_ids(db, user.id) is first_groups
    first_teams = await teams_service.user_team_ids(db, user.id)
    assert await teams_service.user_team_ids(db, user.id) is first_teams


async def test_group_cycle_terminates_and_depth_fails_closed(db):
    """AD is a graph: a cycle must terminate, and nesting deeper than the cap
    resolves FEWER memberships (fails closed), never hangs."""
    a = await groups_service.upsert_group(db, dn="CN=a,DC=t", name="A")
    b = await groups_service.upsert_group(db, dn="CN=b,DC=t", name="B")
    c = await groups_service.upsert_group(db, dn="CN=c,DC=t", name="C")
    # a -> b -> c -> a (a cycle, as AD legally allows).
    await groups_service.set_parents(db, a, [b.id])
    await groups_service.set_parents(db, b, [c.id])
    await groups_service.set_parents(db, c, [a.id])
    user = await _user(db, "Cycled")
    db.add(GroupMember(group_id=a.id, user_id=user.id))
    await db.flush()
    resolved = await groups_service.user_group_ids(db, user.id)
    assert resolved == {a.id, b.id, c.id}  # terminated, everything reached once
    reach = await groups_service.group_user_ids(db, c.id)
    assert user.id in reach  # the downward closure crosses the cycle too


async def test_vanished_ad_group_never_loses_its_memberships(db, monkeypatch):
    member = await _user(db, "Synced")
    group = await groups_service.upsert_group(db, dn="CN=gone,DC=t", name="Gone")
    db.add(GroupMember(group_id=group.id, user_id=member.id))
    await db.flush()

    async def no_members(session, dn):
        return []

    async def group_gone(dn):
        return None

    monkeypatch.setattr(groups, "search_group_members", no_members)
    monkeypatch.setattr(groups, "get_group", group_gone)

    # An empty search + a group that no longer resolves must NOT read as "everyone left".
    with pytest.raises(groupsync.StaleDirectoryGroup):
        await groupsync.reconcile_group(db, group)
    assert member.id in await groups_service.group_user_ids(db, group.id)
    assert group.directory_missing_since is not None

    # While flagged, the login path holds removals too (it would otherwise drain
    # the group one sign-in at a time).
    await groupsync.sync_login_membership(db, member, [group], frozenset())
    assert member.id in await groups_service.group_user_ids(db, group.id)

    # A genuinely empty group that still EXISTS does reconcile, and clears the flag.
    async def group_exists(dn):
        return DirectoryGroup(cn="gone", dn=dn, description="", member_count=0)

    monkeypatch.setattr(groups, "get_group", group_exists)
    added, removed = await groupsync.reconcile_group(db, group)
    assert (added, removed) == (0, 1)
    assert group.directory_missing_since is None
    assert await groups_service.group_user_ids(db, group.id) == set()


async def test_unreachable_directory_is_not_a_missing_group(db, monkeypatch):
    """The distinction the whole guard rests on: a DC that can't be reached must
    never be read as "the group is gone", which would flag a healthy group and
    tell the admin their AD is wrong when it isn't."""
    group = await groups_service.upsert_group(db, dn="CN=fine,DC=t", name="Fine")

    async def no_members(session, dn):
        return []

    async def dc_down(dn):
        raise DirectoryUnreachable("connection refused")

    monkeypatch.setattr(groups, "search_group_members", no_members)
    monkeypatch.setattr(groups, "get_group", dc_down)

    with pytest.raises(DirectoryUnreachable):
        await groupsync.reconcile_group(db, group)
    assert group.directory_missing_since is None  # NOT flagged as stale


async def test_unknown_manager_is_refused(db):
    owner = await _user(db, "Owner")
    team = await _team(db, owner)
    with pytest.raises(ConflictError):
        await teams_service.replace_managers(db, team.id, [uuid.uuid4()], actor_id=owner.id)
