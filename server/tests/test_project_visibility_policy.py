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
from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
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
