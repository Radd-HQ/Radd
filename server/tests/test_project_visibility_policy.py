"""Project visibility is configured through the Baseline role (RADD-935), and it
costs something — pinned so the trade-off is a test, not a paragraph:

1. The seeded Baseline (`item.read@own` + `@participant`) lists every project to
   an account with no grants (`holds_base` is lattice-aware by design).
2. Emptying those atoms lists nothing — reachable today from Settings → Roles.
3. It also hides items the person REPORTED in projects they are not entitled to
   (requester-sourced accounts floor on Requester and are unaffected).

DB-backed; flushed, never committed.
"""

import uuid


from radd.modules.auth import authz, authz_batch, roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

from _factories import make_user


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
    """The default: no grants anywhere, listed against everything, because
    `item.read@own` holds `item.read` in qualified form and the list gates on that."""
    await _baseline(db, ["item.read@own", "item.read@participant"])
    projects = await _projects(db)
    person = await make_user(db)

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
    person = await make_user(db)
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
    """The trade-off, at the ATOM level where the resolver decides: with the
    Baseline emptied, no form of `item.read` remains in an un-granted project, so
    the reporter's own ticket goes too (row filtering never runs; the gate refuses)."""
    elsewhere = (await _projects(db, 1))[0]
    person = await make_user(db)

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
    """You see a project you have something in, and nothing else: the atoms are
    the same qualified Baseline, but the relationship must be real."""
    await _baseline(db, ["item.read@own", "item.read@participant"])
    mine, theirs = await _projects(db)
    person = await make_user(db)
    admin = await make_user(db, role=InstanceRole.ADMIN)
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
    person = await make_user(db)
    assert await authz.visible_projects(db, person) == {}


async def test_a_grant_shows_the_project_with_nothing_in_it(db):
    """Entitlement does not need a relationship. A granted project is yours
    whether or not anyone has filed anything there yet — otherwise a new
    project would be invisible to the team that just got access to it."""
    await _baseline(db, ["item.read@own"])
    granted, _other = await _projects(db)
    person = await make_user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    await db.flush()

    visible = await authz.visible_projects(db, person)
    assert granted.id in visible
    assert Permission.ITEM_READ in visible[granted.id].permissions
    # RADD-1041: entitlement (a grant), not a relationship — tagged ENTITLED.
    assert visible[granted.id].via == authz_batch.ProjectVia.ENTITLED


async def test_the_baseline_lever_still_works_over_the_relationship(db):
    """The resolver requires BOTH the qualified read and the relationship: with the
    Baseline emptied, having an item somewhere confers nothing, so strict
    entitlement stays reachable."""
    await _baseline(db, [])
    mine = (await _projects(db, 1))[0]
    person = await make_user(db)
    admin = await make_user(db, role=InstanceRole.ADMIN)
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
    person = await make_user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    admin = await make_user(db, role=InstanceRole.ADMIN)
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
    """RADD-1041: tagging WHY a project is visible must never change WHICH ones are
    — stripped of `.via` this is the set the test above pins, and a caller ignoring
    `via` gets exactly what `require_anywhere` returns."""
    await _baseline(db, ["item.read@own", "item.read@participant"])
    mine, theirs = await _projects(db)
    person = await make_user(db)
    admin = await make_user(db, role=InstanceRole.ADMIN)
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
    person = await make_user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    admin = await make_user(db, role=InstanceRole.ADMIN)
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
    person = await make_user(db)
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=granted.id))
    admin = await make_user(db, role=InstanceRole.ADMIN)
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
