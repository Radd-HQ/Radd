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
from radd.modules.ldap import groups, groupsync, service as ldap_service
from radd.modules.ldap.groupsync import MemberRow, plan_reconcile
from radd.modules.ldap.types import DirectoryGroup, DirectoryUser
from radd.modules.teams import service as teams_service
from radd.modules.teams.models import TeamMember
from radd.modules.teams.schemas import TeamCreate, TeamUpdate
from radd.modules.teams.types import MemberSource


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


# --- pure reconcile planner ---------------------------------------------------


def test_plan_reconcile_joiner_leaver_manual_untouched():
    joiner, leaver, manual, stays = _uid(), _uid(), _uid(), _uid()
    users = {
        "joiner@ad.example.com": joiner,
        "manual@ad.example.com": manual,
        "stays@ad.example.com": stays,
    }
    rows = [
        MemberRow(user_id=leaver, source=MemberSource.DIRECTORY),  # gone from AD
        MemberRow(user_id=manual, source=MemberSource.MANUAL),  # hand-added, in AD
        MemberRow(user_id=stays, source=MemberSource.DIRECTORY),  # still in AD
    ]
    plan = plan_reconcile(
        ["joiner@ad.example.com", "manual@ad.example.com", "stays@ad.example.com"], rows, users
    )
    assert plan.add_user_ids == {joiner}  # manual row blocks a duplicate directory add
    assert plan.remove_user_ids == {leaver}  # ONLY directory rows are removable


def test_plan_reconcile_manual_row_never_removed():
    manual = _uid()
    rows = [MemberRow(user_id=manual, source=MemberSource.MANUAL)]
    # The manual member is NOT in the directory group — still untouched.
    plan = plan_reconcile(["other@ad.example.com"], rows, {})
    assert plan.add_user_ids == frozenset() and plan.remove_user_ids == frozenset()


def test_plan_reconcile_unknown_members_ignored_and_idempotent():
    known = _uid()
    users = {"known@ad.example.com": known}
    emails = ["known@ad.example.com", "stranger@ad.example.com"]  # stranger: no Radd account
    first = plan_reconcile(emails, [], users)
    assert first.add_user_ids == {known}
    # Apply, then replan: nothing left to do.
    after = [MemberRow(user_id=known, source=MemberSource.DIRECTORY)]
    second = plan_reconcile(emails, after, users)
    assert second.add_user_ids == frozenset() and second.remove_user_ids == frozenset()


def test_plan_reconcile_matches_case_insensitively():
    target = _uid()
    plan = plan_reconcile(["J.Doe@AD.Example.com"], [], {"j.doe@ad.example.com": target})
    assert plan.add_user_ids == {target}


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


async def test_group_import_creates_linked_team_and_honors_provision_flag(
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

    # provision_members=False: team created + linked, ONLY the existing user seated.
    outcomes = await groupsync.import_groups(
        db, [group_dn], provision_members=False, actor_id=admin.id
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.created and outcome.error is None and outcome.cn == "platform"
    assert outcome.members_added == 1 and outcome.users_provisioned == 0
    team = await teams_service.get_team(db, outcome.team_id)
    assert team.directory_group_dn == group_dn and team.directory_group_name == "platform"
    rows = {r.user_id: r.source for r in await teams_service.team_member_rows(db, team.id)}
    assert rows == {existing.id: MemberSource.DIRECTORY.value}
    assert await auth_service.get_user_by_email(db, "stranger@ad.example.com") is None

    # provision_members=True: reuses the linked team, provisions the stranger
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
    rows = {r.user_id: r.source for r in await teams_service.team_member_rows(db, team.id)}
    assert rows[stranger.id] == MemberSource.DIRECTORY.value


async def test_reconcile_team_joiner_leaver_and_idempotent(db, admin, monkeypatch):
    """Spec 87 rewrote the ending of this one. Under spec 84 a linked team could
    carry hand-added rows that no sync would ever touch; linking now hands the
    whole roster to AD, so the pre-existing manual row becomes a directory row and
    is reconciled like any other."""
    group_dn = "CN=render,OU=Groups,DC=ad,DC=example,DC=com"
    team = await teams_service.create_team(db, TeamCreate(name="Render"))
    joiner = await auth_service.create_user(
        db, UserCreate(email="joiner@ad.example.com", name="Joiner", password="password-123")
    )
    leaver = await auth_service.create_user(
        db, UserCreate(email="leaver@ad.example.com", name="Leaver", password="password-123")
    )
    manual = await auth_service.create_user(
        db, UserCreate(email="manual@ad.example.com", name="Manual", password="password-123")
    )
    # Hand-added while the team is still local — the only way this row can exist.
    await teams_service.add_team_member(db, team.id, manual.id, actor_id=admin.id)
    await teams_service.update_team(
        db, team.id, TeamUpdate(directory_group_dn=group_dn, directory_group_name="render")
    )
    # Linking re-sourced the roster: nothing is frozen outside the sync's reach.
    rows = {r.user_id: r.source for r in await teams_service.team_member_rows(db, team.id)}
    assert rows == {manual.id: MemberSource.DIRECTORY.value}
    # …and membership is now read-only here.
    with pytest.raises(ConflictError):
        await teams_service.add_team_member(db, team.id, joiner.id, actor_id=admin.id)

    db.add(TeamMember(team_id=team.id, user_id=leaver.id, source=MemberSource.DIRECTORY))
    await db.flush()

    directory = [_directory_user("joiner"), _directory_user("manual")]

    async def fake_members(session, dn):  # spec 85: wrappers resolve the base off a session
        assert dn == group_dn
        return directory

    monkeypatch.setattr(groups, "search_group_members", fake_members)

    added, removed = await groupsync.reconcile_team(db, team, actor_id=admin.id)
    assert (added, removed) == (1, 1)
    rows = {r.user_id: r.source for r in await teams_service.team_member_rows(db, team.id)}
    assert rows == {
        joiner.id: MemberSource.DIRECTORY.value,
        manual.id: MemberSource.DIRECTORY.value,  # in the group, so it stays
    }
    # Idempotent: a second run changes nothing.
    assert await groupsync.reconcile_team(db, team, actor_id=admin.id) == (0, 0)

    # Unlinking is the escape hatch: the roster comes back as manual, so nobody
    # loses access the moment the link goes.
    await teams_service.update_team(db, team.id, TeamUpdate(directory_group_dn=None))
    rows = {r.user_id: r.source for r in await teams_service.team_member_rows(db, team.id)}
    assert set(rows.values()) == {MemberSource.MANUAL.value}
    await teams_service.add_team_member(db, team.id, leaver.id, actor_id=admin.id)  # editable again


async def test_login_membership_sync_joins_and_leaves_directory_rows(db, admin):
    dn_in = "CN=in,OU=Groups,DC=ad,DC=example,DC=com"
    dn_out = "CN=out,OU=Groups,DC=ad,DC=example,DC=com"
    team_in = await teams_service.create_team(
        db, TeamCreate(name="In")
    )
    team_out = await teams_service.create_team(
        db, TeamCreate(name="Out")
    )
    await teams_service.update_team(
        db, team_in.id, TeamUpdate(directory_group_dn=dn_in, directory_group_name="in")
    )
    await teams_service.update_team(
        db, team_out.id, TeamUpdate(directory_group_dn=dn_out, directory_group_name="out")
    )
    user = await auth_service.create_user(
        db, UserCreate(email="binder@ad.example.com", name="Binder", password="password-123")
    )
    db.add(TeamMember(team_id=team_out.id, user_id=user.id, source=MemberSource.DIRECTORY))
    await db.flush()

    linked = await teams_service.linked_teams(db)
    await groupsync.sync_login_membership(db, user, linked, frozenset({dn_in}))
    in_rows = {r.user_id for r in await teams_service.team_member_rows(db, team_in.id)}
    out_rows = {r.user_id for r in await teams_service.team_member_rows(db, team_out.id)}
    assert user.id in in_rows and user.id not in out_rows
    # Idempotent on a repeat login with the same memberships.
    await groupsync.sync_login_membership(db, user, linked, frozenset({dn_in}))
    assert {r.user_id for r in await teams_service.team_member_rows(db, team_in.id)} == in_rows


async def test_ldap_find_or_create_claims_unknown_source(db):
    email = f"ad84-unknown-{uuid.uuid4().hex[:8]}@ad.example.com"
    orphan = User(email=email, name="Pre 84", password_hash=None, source=UserSource.UNKNOWN)
    db.add(orphan)
    await db.flush()
    du = DirectoryUser(username="pre84", email=email, name="Pre 84", is_admin=False)
    user, created = await ldap_service.find_or_create_user(db, du)
    assert not created and user.id == orphan.id and user.source == UserSource.LDAP
