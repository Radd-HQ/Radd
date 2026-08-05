"""AD/LDAP depth (spec 84): the pure reconcile planner, the duplicates
heuristic, instance-admin user administration (deactivate revokes sessions,
self-deactivate 409), and the group-import/reconcile services with the
directory stubbed at the service seam (ldap3 never touches the wire — the
spec-42/49 test gate: no directory in CI).

DB-backed (compose Postgres) — flushed, never committed; the session rolls
back at teardown."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User, UserSession
from radd.modules.auth.schemas import UserAdminUpdate, UserCreate
from radd.modules.auth.types import DuplicateKind, InstanceRole, UserSource
from radd.modules.groups import service as groups_service
from radd.modules.groups.models import GroupMember
from radd.modules.ldap import groups, groupsync, service as ldap_service
from radd.modules.ldap.types import DirectoryGroup, DirectoryUser
from radd.modules.teams import service as teams_service


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
        email=f"ad84-admin-{uuid.uuid4().hex[:8]}@example.com",
        name="AD Depth Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


def _uid() -> uuid.UUID:
    return uuid.uuid4()


# (RADD-829 retired the pure reconcile planner: group_members has no manual
# path, so the joiner/leaver/manual algebra collapsed into a set replace —
# `groups.service.replace_members` — tested through the flows below.)


# --- duplicates heuristic -----------------------------------------------------


def _user(email: str, name: str, active: bool = True) -> User:
    return User(id=_uid(), email=email, name=name, active=active)


def test_duplicate_groups_by_email_local_part_and_name():
    a = _user("j.doe@ad.example.com", "Jane Doe")
    b = _user("j.doe@example.com", "Jane D")  # same local part, other domain
    c = _user("jane@example.com", "Jane Doe", active=False)  # same NAME as a, inactive
    d = _user("solo@example.com", "Solo Person")
    groups_found = auth_service.find_duplicate_groups([a, b, c, d])
    by_kind = {(kind, key): users for kind, key, users in groups_found}
    assert {u.id for u in by_kind[(DuplicateKind.EMAIL_LOCAL_PART, "j.doe")]} == {a.id, b.id}
    assert {u.id for u in by_kind[(DuplicateKind.NAME, "jane doe")]} == {a.id, c.id}
    # Inactive accounts are included (flagged by their own `active`), singletons never group.
    assert all(d.id not in {u.id for u in users} for users in by_kind.values())


def test_duplicate_groups_identical_membership_reported_once():
    a = _user("dupe@x.example.com", "Same Name")
    b = _user("dupe@y.example.com", "Same Name")
    found = auth_service.find_duplicate_groups([a, b])
    assert len(found) == 1
    kind, key, users = found[0]
    assert kind is DuplicateKind.EMAIL_LOCAL_PART and key == "dupe"


def test_transitive_member_filter_excludes_disabled_accounts_per_setting():
    """RADD-831 Done-when: `ldap_exclude_disabled` applies to group-member
    resolution too — a disabled account must not arrive as a group member."""
    dn = "CN=Artists,OU=Groups,DC=x"
    on = groups.transitive_group_members_filter(dn, exclude_disabled=True)
    off = groups.transitive_group_members_filter(dn, exclude_disabled=False)
    assert ldap_service.DISABLED_ACCOUNT_CLAUSE in on
    assert ldap_service.DISABLED_ACCOUNT_CLAUSE not in off
    assert dn.replace("=", "\\3d") in on or dn in on  # the group DN still anchors the probe


# --- user administration (DB) -------------------------------------------------


async def test_deactivate_revokes_sessions_and_blocks_self(db, admin):
    victim = await auth_service.create_user(
        db,
        UserCreate(
            email=f"ad84-victim-{uuid.uuid4().hex[:8]}@example.com",
            name="Victim",
            password="password-123",
        ),
    )
    assert victim.source == UserSource.LOCAL
    await auth_service.create_session(db, victim)
    assert victim.last_login_at is not None  # stamped by the one login seam
    await auth_service.update_user_admin(
        db, victim.id, UserAdminUpdate(active=False, name="Renamed Victim"), admin
    )
    assert victim.active is False and victim.name == "Renamed Victim"
    remaining = (
        await db.execute(select(UserSession).where(UserSession.user_id == victim.id))
    ).scalars().all()
    assert remaining == []  # deactivation revoked the session
    with pytest.raises(ConflictError):
        await auth_service.update_user_admin(db, admin.id, UserAdminUpdate(active=False), admin)


async def test_instance_role_patch_and_self_demotion_guard(db, admin):
    """Spec 86: PATCH /users/{id} carries instance_role — THE role ladder now
    that the workspace-members endpoints are gone. Self-demotion is a 409."""
    member = await auth_service.create_user(
        db,
        UserCreate(
            email=f"ad86-role-{uuid.uuid4().hex[:8]}@example.com",
            name="Ladder",
            password="password-123",
        ),
    )
    promoted = await auth_service.update_user_admin(
        db, member.id, UserAdminUpdate(instance_role=InstanceRole.ADMIN), admin
    )
    assert promoted.instance_role == InstanceRole.ADMIN.value
    demoted = await auth_service.update_user_admin(
        db, member.id, UserAdminUpdate(instance_role=InstanceRole.MEMBER), admin
    )
    assert demoted.instance_role == InstanceRole.MEMBER.value
    # No-op patch of your own current role is fine; DEMOTING yourself is not.
    await auth_service.update_user_admin(
        db, admin.id, UserAdminUpdate(instance_role=InstanceRole.ADMIN), admin
    )
    with pytest.raises(ConflictError):
        await auth_service.update_user_admin(
            db, admin.id, UserAdminUpdate(instance_role=InstanceRole.MEMBER), admin
        )


async def test_list_users_filters(db, admin):
    marker = uuid.uuid4().hex[:8]
    await auth_service.create_user(
        db,
        UserCreate(email=f"ad84-filter-{marker}@example.com", name=f"Filter {marker}", password="password-123"),
    )
    hits = await auth_service.list_users(db, q=f"filter-{marker}")
    assert [u.name for u in hits] == [f"Filter {marker}"]
    assert await auth_service.list_users(db, q=f"filter-{marker}", source=UserSource.LDAP) == []
    assert await auth_service.list_users(db, q=f"filter-{marker}", active=False) == []


# --- directory-backed flows with the wire stubbed at the service seam ---------


def _directory_user(local: str) -> DirectoryUser:
    return DirectoryUser(
        username=local, email=f"{local}@ad.example.com", name=local.title(), is_admin=False
    )


async def test_group_import_mirrors_group_team_holds_it_and_honors_provision_flag(
    db, admin, monkeypatch
):
    group_dn = "CN=platform,OU=Groups,DC=ad,DC=example,DC=com"
    existing = await auth_service.create_user(
        db,
        UserCreate(email="known@ad.example.com", name="Known One", password="password-123"),
    )
    members = [_directory_user("known"), _directory_user("stranger")]

    async def fake_get_group(dn):
        assert dn == group_dn
        return DirectoryGroup(cn="platform", dn=group_dn, description="", member_count=2)

    async def fake_members(session, dn):  # spec 85: wrappers resolve the base off a session
        assert dn == group_dn
        return members

    monkeypatch.setattr(groups, "get_group", fake_get_group)
    monkeypatch.setattr(groups, "search_group_members", fake_members)

    # provision_members=False (RADD-829): the GROUP is mirrored, a team of the
    # same name HOLDS it, and only the existing user is seated.
    outcomes = await groupsync.import_groups(
        db, [group_dn], provision_members=False, actor_id=admin.id
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.created and outcome.error is None and outcome.cn == "platform"
    assert outcome.members_added == 1 and outcome.users_provisioned == 0
    group = await groups_service.group_by_dn(db, group_dn)
    assert group is not None and group.name == "platform"
    team = await teams_service.get_team(db, outcome.team_id)
    assert [g.id for g in await teams_service.team_groups(db, team.id)] == [group.id]
    assert {u.id for u in await teams_service.list_team_members(db, team.id)} == {existing.id}
    assert await auth_service.get_user_by_email(db, "stranger@ad.example.com") is None

    # provision_members=True: reuses the group + team, provisions the stranger
    # (SSO-only, source=ldap; a new active user holds the global member floor).
    outcomes = await groupsync.import_groups(
        db, [group_dn], provision_members=True, actor_id=admin.id
    )
    outcome = outcomes[0]
    assert outcome.team_id == team.id and not outcome.created
    assert outcome.users_provisioned == 1 and outcome.members_added == 1
    stranger = await auth_service.get_user_by_email(db, "stranger@ad.example.com")
    assert stranger is not None
    assert stranger.password_hash is None and stranger.source == UserSource.LDAP
    assert stranger.active  # spec 86: a new active user holds the global member floor
    assert stranger.id in await groups_service.group_user_ids(db, group.id)


async def test_reconcile_group_joiner_leaver_and_idempotent(db, admin, monkeypatch):
    """RADD-829: group membership is wholly sync-owned — a reconcile is a set
    replace against the directory's transitive answer."""
    group_dn = "CN=render,OU=Groups,DC=ad,DC=example,DC=com"
    group = await groups_service.upsert_group(db, dn=group_dn, name="render")
    joiner = await auth_service.create_user(
        db, UserCreate(email="joiner@ad.example.com", name="Joiner", password="password-123")
    )
    leaver = await auth_service.create_user(
        db, UserCreate(email="leaver@ad.example.com", name="Leaver", password="password-123")
    )
    db.add(GroupMember(group_id=group.id, user_id=leaver.id))
    await db.flush()

    directory = [_directory_user("joiner"), _directory_user("stranger")]

    async def fake_members(session, dn):  # spec 85: wrappers resolve the base off a session
        assert dn == group_dn
        return directory

    async def fake_get_group(dn):
        return DirectoryGroup(cn="render", dn=dn, description="", member_count=2)

    monkeypatch.setattr(groups, "search_group_members", fake_members)
    monkeypatch.setattr(groups, "get_group", fake_get_group)

    # Joiner in, leaver out; the stranger (no Radd account) is never provisioned
    # by a reconcile.
    added, removed = await groupsync.reconcile_group(db, group)
    assert (added, removed) == (1, 1)
    assert await groups_service.group_user_ids(db, group.id) == {joiner.id}
    assert await auth_service.get_user_by_email(db, "stranger@ad.example.com") is None
    # Idempotent: a second run changes nothing.
    assert await groupsync.reconcile_group(db, group) == (0, 0)


async def test_reconcile_mirrors_nesting_edges_between_mirrored_groups(db, monkeypatch):
    """RADD-831: the sync fetches group→group edges — the structure the old
    transitive-only resolution threw away. Only edges between MIRRORED groups
    are representable; an unmirrored parent DN is silently absent."""
    parent = await groups_service.upsert_group(db, dn="CN=parent,DC=e", name="parent")
    child = await groups_service.upsert_group(db, dn="CN=child,DC=e", name="child")

    async def fake_get_group(dn):
        member_of = ("CN=parent,DC=e", "CN=unmirrored,DC=e") if dn == child.dn else ()
        return DirectoryGroup(cn=dn.split(",")[0][3:], dn=dn, description="", member_count=0, member_of=member_of)

    async def no_members(session, dn):
        return []

    monkeypatch.setattr(groups, "get_group", fake_get_group)
    monkeypatch.setattr(groups, "search_group_members", no_members)

    await groupsync.reconcile_group(db, child)
    user = await auth_service.create_user(
        db, UserCreate(email="edge@ad.example.com", name="Edge", password="password-123")
    )
    db.add(GroupMember(group_id=child.id, user_id=user.id))
    await db.flush()
    # Membership of the child now reaches the parent through the mirrored edge.
    resolved = await groups_service.user_group_ids(db, user.id)
    assert {child.id, parent.id} <= resolved


async def test_login_membership_sync_joins_and_leaves_group_rows(db, admin):
    dn_in = "CN=in,OU=Groups,DC=ad,DC=example,DC=com"
    dn_out = "CN=out,OU=Groups,DC=ad,DC=example,DC=com"
    group_in = await groups_service.upsert_group(db, dn=dn_in, name="in")
    group_out = await groups_service.upsert_group(db, dn=dn_out, name="out")
    user = await auth_service.create_user(
        db, UserCreate(email="binder@ad.example.com", name="Binder", password="password-123")
    )
    db.add(GroupMember(group_id=group_out.id, user_id=user.id))
    await db.flush()

    mirrored = await groups_service.list_groups(db)
    await groupsync.sync_login_membership(db, user, mirrored, frozenset({dn_in}))
    assert user.id in await groups_service.group_user_ids(db, group_in.id)
    assert user.id not in await groups_service.group_user_ids(db, group_out.id)
    # Idempotent on a repeat login with the same memberships.
    await groupsync.sync_login_membership(db, user, mirrored, frozenset({dn_in}))
    assert user.id in await groups_service.group_user_ids(db, group_in.id)
