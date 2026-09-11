"""What an operator can actually configure about project VISIBILITY (RADD-935).

The question this answers: "how do I make it so people cannot list or view
projects they don't have access to?"

The lever is the **Baseline role**, and it is a genuine one — but it is coupled
to something an operator probably does not want to give up, and that coupling is
the whole point of this file. It pins three facts so the trade-off is a test
rather than a paragraph somebody has to re-derive:

1. With the seeded Baseline (`item.read@own` + `item.read@participant`), an
   account with NO grants is listed against every project. That is not a bug in
   `require_anywhere` — `holds_base` is lattice-aware by design (RADD-823) and
   the person genuinely may read their own rows there.

2. Emptying those atoms from the Baseline is sufficient: the same account is
   then listed against nothing. So the policy IS reachable today, with no code
   change, from Settings → Roles.

3. It costs the thing they were there for. With them gone, a person can no
   longer see an item they REPORTED in a project they are not entitled to — the
   service-desk "my own tickets" case. Email-provisioned accounts are unaffected
   (they floor on the seeded Requester role, RADD-828), but staff-shaped accounts
   are.

If both are wanted at once — "cannot enumerate projects" AND "sees their own
tickets" — no configuration expresses it and RADD-935 is the change that would.

DB-backed; flushed, never committed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import authz, authz_batch, roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
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


async def _user(db, role=InstanceRole.MEMBER) -> User:
    user = User(
        email=f"vis-{uuid.uuid4().hex[:8]}@example.com",
        name="Visibility Probe",
        instance_role=role.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _baseline(db, permissions: list[str]):
    await auth_roles.ensure_builtin_roles(db)
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = permissions
    await db.flush()
    authz.forget_baseline(db)


async def _projects(db, count: int = 2):
    return [
        await projects_service.create_project(
            db, ProjectCreate(key=f"VZ{uuid.uuid4().hex[:4].upper()}", name=f"P{i}")
        )
        for i in range(count)
    ]


async def test_own_item_baseline_lists_every_project(db):
    """The default: no grants anywhere, listed against everything.

    This is what makes an account with every grant revoked still show 97
    projects in the rail — `item.read@own` holds `item.read` in qualified form,
    and the project list gates on exactly that.
    """
    await _baseline(db, ["item.read@own", "item.read@participant"])
    projects = await _projects(db)
    person = await _user(db)

    reach = await authz.require_anywhere(db, person, Permission.ITEM_READ)
    assert {p.id for p in projects} <= set(reach), (
        "the seeded Baseline reaches every project — this is the documented "
        "starting point, not a regression"
    )
    # …and it is qualified reach, which is the distinction RADD-933 surfaced.
    for permissions in reach.values():
        assert Permission.ITEM_READ not in permissions


async def test_emptying_the_baseline_hides_unentitled_projects(db):
    """The lever: strip the own-item atoms and only granted projects are listed."""
    await _baseline(db, [])
    granted, hidden = await _projects(db)
    person = await _user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(
        GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id)
    )
    await db.flush()

    reach = await authz.require_anywhere(db, person, Permission.ITEM_READ)
    assert granted.id in reach
    assert hidden.id not in reach, "an un-granted project must not be listed"
    # The granted one is FULL read, not qualified — the rail lists it (RADD-934).
    assert Permission.ITEM_READ in reach[granted.id]


async def test_the_lever_costs_the_own_item_read_it_was_there_for(db):
    """The trade-off, as a test so it is not discovered in production.

    Asserted at the ATOM level, which is where the resolver decides: with the
    Baseline emptied, a person holds no form of `item.read` in a project they
    have no grant on, so the reporter's view of their own ticket goes with the
    project enumeration. (Row filtering — `WHERE reporter_id = actor` — is
    downstream of this and never runs, because the gate refuses first.)

    Email-provisioned accounts floor on the seeded Requester role instead
    (RADD-828), so a genuine external requester is unaffected; this is the cost
    for staff-shaped accounts.
    """
    elsewhere = (await _projects(db, 1))[0]
    person = await _user(db)

    await _baseline(db, ["item.read@own", "item.read@participant"])
    with_own = await authz.effective_permissions(db, person, project=elsewhere)
    assert authz.holds_base(with_own, Permission.ITEM_READ)
    assert Permission.ITEM_READ not in with_own  # qualified only, never full

    await _baseline(db, [])
    without_own = await authz.effective_permissions(db, person, project=elsewhere)
    assert not authz.holds_base(without_own, Permission.ITEM_READ), (
        "stripping the Baseline also removes the reporter's read of their own "
        "ticket — the coupling RADD-935 exists to break"
    )


# --- RADD-937: visibility follows the work ------------------------------------


async def test_a_relationship_makes_one_project_visible_and_not_the_rest(db):
    """The model the operator asked for: you see a project you have something
    in, and nothing else.

    Before this, the qualified Baseline listed BOTH projects — "your own rows,
    anywhere" covered everywhere. The atoms are unchanged; what changed is that
    the relationship must be real.
    """
    await _baseline(db, ["item.read@own", "item.read@participant"])
    mine, theirs = await _projects(db)
    person = await _user(db)
    admin = await _user(db, InstanceRole.ADMIN)
    created = await items.create_item(
        db, ItemCreate(project_id=mine.id, title="a ticket I filed"), admin
    )
    # Reported BY the person — the @own relation (RADD-823 D6).
    item_row = await db.get(WorkItem, created.id)
    item_row.reporter_id = person.id
    await db.flush()

    visible = await authz.visible_projects(db, person)
    assert mine.id in visible, "a project holding their own item must be visible"
    assert theirs.id not in visible, (
        "a project they have nothing in must not be — this is the 97-projects bug"
    )
    # RADD-1041: this is exactly the RELATED half — qualified read + a real
    # relationship, no grant.
    assert visible[mine.id].via == authz_batch.ProjectVia.RELATED


async def test_no_relationship_and_no_grant_sees_nothing(db):
    """The account the whole thread started from, at its cleanest."""
    await _baseline(db, ["item.read@own", "item.read@participant"])
    await _projects(db)
    person = await _user(db)
    assert await authz.visible_projects(db, person) == {}


async def test_a_grant_shows_the_project_with_nothing_in_it(db):
    """Entitlement does not need a relationship. A granted project is yours
    whether or not anyone has filed anything there yet — otherwise a new
    project would be invisible to the team that just got access to it."""
    await _baseline(db, ["item.read@own"])
    granted, _other = await _projects(db)
    person = await _user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    await db.flush()

    visible = await authz.visible_projects(db, person)
    assert granted.id in visible
    assert Permission.ITEM_READ in visible[granted.id].permissions
    # RADD-1041: entitlement (a grant), not a relationship — tagged ENTITLED.
    assert visible[granted.id].via == authz_batch.ProjectVia.ENTITLED


async def test_the_baseline_lever_still_works_over_the_relationship(db):
    """RADD-935's operator lever survives: with no qualified read at all, having
    an item somewhere confers nothing, because they could not read it anyway.

    This is why the resolver requires BOTH — take the qualifier away and the
    relationship stops mattering, so an operator who wants strict entitlement
    can still have it.
    """
    await _baseline(db, [])
    mine = (await _projects(db, 1))[0]
    person = await _user(db)
    admin = await _user(db, InstanceRole.ADMIN)
    created = await items.create_item(
        db, ItemCreate(project_id=mine.id, title="unreadable to them"), admin
    )
    item_row = await db.get(WorkItem, created.id)
    item_row.reporter_id = person.id
    await db.flush()

    assert await authz.visible_projects(db, person) == {}


# --- RADD-1041: `via` is presentation, never a second decision ----------------


async def test_via_tags_entitled_and_related_separately(db):
    """The exact split `visible_projects` already computes (RADD-937), now named
    per row: a granted project reads ENTITLED, an unentitled project reached
    only through the person's own item reads RELATED — both present at once,
    on the same relationship the RADD-937 tests above already proved correct."""
    await _baseline(db, ["item.read@own", "item.read@participant"])
    granted, mine = await _projects(db, 2)
    person = await _user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    admin = await _user(db, InstanceRole.ADMIN)
    created = await items.create_item(
        db, ItemCreate(project_id=mine.id, title="a ticket I filed"), admin
    )
    item_row = await db.get(WorkItem, created.id)
    item_row.reporter_id = person.id
    await db.flush()

    visible = await authz.visible_projects(db, person)
    assert visible[granted.id].via == authz_batch.ProjectVia.ENTITLED
    assert visible[mine.id].via == authz_batch.ProjectVia.RELATED


async def test_via_is_additive_and_never_narrows_the_visible_set(db):
    """RADD-1041's whole safety property: tagging WHY a project is visible must
    never change WHICH projects are, or what a caller ignoring `.via` sees.

    Stripped of `.via`, the id set here is exactly what RADD-937's
    `test_a_relationship_makes_one_project_visible_and_not_the_rest` already
    pins — this test exists so a future change to the tagging logic cannot
    quietly start FILTERING instead of just labeling, and so a caller that
    predates `via` (every one of them, today) keeps resolving the identical
    permission set `require_anywhere` would hand back directly.
    """
    await _baseline(db, ["item.read@own", "item.read@participant"])
    mine, theirs = await _projects(db)
    person = await _user(db)
    admin = await _user(db, InstanceRole.ADMIN)
    created = await items.create_item(
        db, ItemCreate(project_id=mine.id, title="a ticket I filed"), admin
    )
    item_row = await db.get(WorkItem, created.id)
    item_row.reporter_id = person.id
    await db.flush()

    visible = await authz.visible_projects(db, person)
    # The RADD-937 decision, unchanged: exactly the project holding their item.
    assert set(visible) == {mine.id}
    assert theirs.id not in visible
    # A caller that ignores `.via` entirely — every pre-1041 caller — still
    # gets the identical permission set RADD-937 resolved through `require_anywhere`.
    reachable = await authz.require_anywhere(db, person, Permission.ITEM_READ)
    assert visible[mine.id].permissions == reachable[mine.id]


async def test_get_projects_endpoint_surfaces_via(db):
    """Router-level: `GET /projects` (`projects.router.list_projects`) threads
    the same entitled/related split onto `ProjectRead.via` — proof the wiring
    from `visible_projects` through the endpoint actually works, not just the
    service function underneath it."""
    from radd.modules.projects.router import list_projects as get_projects

    await _baseline(db, ["item.read@own", "item.read@participant"])
    granted, mine = await _projects(db, 2)
    person = await _user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    admin = await _user(db, InstanceRole.ADMIN)
    created = await items.create_item(
        db, ItemCreate(project_id=mine.id, title="a ticket I filed"), admin
    )
    item_row = await db.get(WorkItem, created.id)
    item_row.reporter_id = person.id
    await db.flush()

    from fastapi import Response
    rows = await get_projects(db, person, Response())
    by_id = {row.id: row for row in rows}
    assert by_id[granted.id].via == authz_batch.ProjectVia.ENTITLED.value
    assert by_id[mine.id].via == authz_batch.ProjectVia.RELATED.value


async def test_hide_related_pages_do_not_remove_direct_access_or_summary(db):
    from radd.modules.projects import directory
    await _baseline(db, ["item.read@own"])
    granted, mine = await _projects(db, 2)
    person = await _user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    admin = await _user(db, InstanceRole.ADMIN)
    created = await items.create_item(db, ItemCreate(project_id=mine.id, title="My work"), admin)
    item = await db.get(WorkItem, created.id)
    item.reporter_id = person.id
    await db.flush()
    page, total = await directory.page(db, person, hide_related=True, limit=1)
    assert total == 1 and [p.id for p in page] == [granted.id]
    summary = await directory.summary(db, person)
    assert summary.total == 2 and summary.related_count == 1
    direct = await directory.by_identity(db, person, identifier=mine.id)
    assert direct.id == mine.id and direct.via == "related"
