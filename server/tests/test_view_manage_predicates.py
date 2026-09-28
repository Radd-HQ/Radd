"""RADD-1428: the three answers to "may this actor manage an owner-less view"
come from one predicate.

`_require_manage` (the gate), `_hydrate`'s `can_manage` (what the SPA renders)
and `_can_manage_view` (the /grants router's hook) each decided owner-less
views on their own. On a project view they agreed; on an ALL-PROJECTS view the
gate asked `require_anywhere` (RADD-788: holding the atom in any project) while
both descriptions asked for the GLOBAL atom — so a member holding `view.update`
in one project got a Delete the UI never showed, and the sharing editor refused
a grant edit the same member could make over the API. Rolled-back transactions
on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ForbiddenError
from radd.modules.auth import grants, roles as roles_service
from radd.modules.auth.models import User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import InstanceRole, Permission
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.views import service as views_service
from radd.modules.views.models import View
from radd.modules.views.types import ShareLevel, ViewType


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _member(db, name: str) -> User:
    user = User(
        email=f"vm-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"VM{uuid.uuid4().hex[:4].upper()}", name="View scope")
    )


async def _view_manager_in(db, project) -> User:
    """A member holding `view.update` in ONE project, through a project-scoped
    role grant — the principal the three predicates disagreed about."""
    holder = await _member(db, "View manager")
    role = await roles_service.create_role(
        db,
        RoleCreate(
            key=f"vm-{uuid.uuid4().hex[:8]}",
            name="View manager",
            permissions=[str(Permission.VIEW_UPDATE)],
        ),
    )
    await grants.create_grant(db, role.id, user_id=holder.id, project_id=project.id)
    return holder


async def _seeded_view(db, *, project_id=None) -> View:
    """A pre-spec-57 view: no owner, visible to everyone, managed by RBAC atoms."""
    view = View(
        name=f"Seeded {uuid.uuid4().hex[:6]}",
        view_type=ViewType.LIST.value,
        query="",
        owner_id=None,
        project_id=project_id,
        global_access=ShareLevel.VIEWER.value,
    )
    db.add(view)
    await db.flush()
    return view


async def _answers(db, actor, view) -> tuple[bool, bool, bool]:
    """(the gate, the hydrated `can_manage`, the /grants hook) — the three
    places that answer the question. The claim under test is that they agree."""
    try:
        await views_service._require_manage(
            db, view.id, actor, legacy_atom=Permission.VIEW_UPDATE
        )
        gate = True
    except ForbiddenError:
        gate = False
    described = (await views_service._hydrate_one(db, actor, view)).can_manage
    hook = await views_service._can_manage_view(db, actor, str(view.id), None)
    return gate, described, hook


async def test_an_all_projects_view_is_judged_by_holding_the_atom_anywhere(db):
    project = await _project(db)
    holder = await _view_manager_in(db, project)
    bystander = await _member(db, "Bystander")
    view = await _seeded_view(db)

    # RADD-788's bar, now reported the way it is enforced.
    assert await _answers(db, holder, view) == (True, True, True)
    assert await _answers(db, bystander, view) == (False, False, False)


async def test_a_project_view_is_judged_in_its_own_project(db):
    here, elsewhere = await _project(db), await _project(db)
    holder = await _view_manager_in(db, here)

    assert await _answers(db, holder, await _seeded_view(db, project_id=here.id)) == (
        True, True, True,
    )
    # A grant in one project says nothing about a view in another.
    assert await _answers(db, holder, await _seeded_view(db, project_id=elsewhere.id)) == (
        False, False, False,
    )
