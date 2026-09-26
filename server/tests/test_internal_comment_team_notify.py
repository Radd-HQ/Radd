"""RADD-1391: a team-narrowed internal comment notifies only its teams.

Spec 50 lets an internal comment be restricted to teams, and the notify consumer
has a check for it — but the planner never copied `visible_to_teams` into the
notification's detail, so the check saw no teams and admitted every holder of
`comment.read_internal`, whose inbox then carried the comment's excerpt.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.notify import planner
from radd.modules.notify.consumer import _allowed
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name: str, role: str = "member") -> User:
    user = User(email=f"ict-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role=role)
    db.add(user)
    await db.flush()
    return user


async def _grant(db, user: User, project, atoms: list[str]) -> None:
    role = await auth_roles.create_role(
        db, RoleCreate(key=f"ict{uuid.uuid4().hex[:6]}", name="R", permissions=atoms)
    )
    db.add(GlobalRoleGrant(project_id=project.id, user_id=user.id, role_id=role.id))
    await db.flush()


async def test_a_team_narrowed_internal_comment_reaches_only_its_team(db):
    await auth_roles.ensure_builtin_roles(db)
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = []
    await db.flush()
    authz.forget_baseline(db)

    admin = await _user(db, "ICT Admin", role="admin")
    insider = await _user(db, "Insider")
    outsider = await _user(db, "Outsider")
    manager = await _user(db, "Manager")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"IC{uuid.uuid4().hex[:4].upper()}", name="ICT")
    )
    team = await teams_service.create_team(db, TeamCreate(name=f"ICT {uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, insider.id)
    for person in (insider, outsider):
        await _grant(db, person, project, ["item.read", "comment.read_internal"])
    await _grant(db, manager, project, ["item.read", "comment.read_internal", "project.manage"])
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="secret work"), admin)
    row = await db.get(WorkItem, item.id)

    payload = {"excerpt": "only for the team", "visibility": "internal", "visible_to_teams": [str(team.id)]}
    audience = planner.Audience(participating=frozenset({insider.id, outsider.id, manager.id}))
    plan = planner.plan_comment_created(payload, admin.id, audience, frozenset({outsider.id}))

    # Every planned row — the mention included — carries the teams the check needs.
    assert plan.notifications
    assert all(n.detail.get("visible_to_teams") == [str(team.id)] for n in plan.notifications)
    verdicts = {}
    for planned in plan.notifications:
        verdicts[planned.user_id] = await _allowed(db, planned, project, row)
    assert verdicts[insider.id] is True
    assert verdicts[outsider.id] is False, "the excerpt must not reach someone outside the team"
    assert verdicts[manager.id] is True, "project managers read every internal comment"

    # Without the narrowing, the same outsider IS an internal reader — the refusal
    # above comes from the teams, not from a missing permission.
    open_plan = planner.plan_comment_created(
        {"excerpt": "for every internal reader", "visibility": "internal"},
        admin.id, audience, frozenset(),
    )
    outsider_row = next(n for n in open_plan.notifications if n.user_id == outsider.id)
    assert await _allowed(db, outsider_row, project, row) is True
