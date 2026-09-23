"""Cycles have a home project (RADD-1291).

A cycle stays cross-project — any project's issues may sit in it — but it
belongs somewhere: the home project's managers run it without being cycle
admins for the whole instance, and a project's cycle list is what it plans
with (homed there, or holding its issues), not every sprint on the instance.

HTTP-level through the real router (the gate is the router's), DB-backed and
rolled back. A scoped key stands in for a project manager with no cycle atoms.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError
from radd.modules.auth.models import User
from radd.modules.auth.scopes import parse_scope
import importlib

from radd.modules.cycles import directory
from radd.modules.cycles.schemas import CycleCreate, CycleUpdate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

# The package re-exports its APIRouter as `router`; the route functions live in the module.
cycles_router = importlib.import_module("radd.modules.cycles.router")


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _project(db, stem):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"{stem}{uuid.uuid4().hex[:4].upper()}", name=stem))


async def _user(db, scope=None):
    user = User(email=f"cyc-{uuid.uuid4().hex[:8]}@example.com", name="U", instance_role="admin")
    db.add(user)
    await db.flush()
    if scope is not None:
        user.token_scope = parse_scope(scope)
    return user


async def test_a_project_manager_runs_their_projects_cycles_and_nothing_else(db):
    mine, theirs = await _project(db, "MN"), await _project(db, "TH")
    lead = await _user(db, {"projects": {str(mine.id): ["project.manage", "item.read"]}, "global": ["cycle.read"]})

    homed = await cycles_router.create_cycle(CycleCreate(name="Sprint 1", project_id=mine.id), db, lead)
    assert homed.project_id == mine.id
    await cycles_router.update_cycle(homed.id, CycleUpdate(goal="Ship it"), db, lead)

    with pytest.raises(ForbiddenError):  # an instance cycle needs the instance atom
        await cycles_router.create_cycle(CycleCreate(name="Everyone"), db, lead)
    with pytest.raises(ForbiddenError):  # another project's cycle is not theirs to make
        await cycles_router.create_cycle(CycleCreate(name="Theirs", project_id=theirs.id), db, lead)
    with pytest.raises(ForbiddenError):  # nor to receive by re-homing
        await cycles_router.update_cycle(homed.id, CycleUpdate(project_id=theirs.id), db, lead)

    await cycles_router.delete_cycle(homed.id, db, lead)


async def test_a_projects_cycles_are_its_own_plus_those_holding_its_issues(db):
    mine, theirs = await _project(db, "MN"), await _project(db, "TH")
    admin = await _user(db)
    own = await cycles_router.create_cycle(CycleCreate(name="Own", project_id=mine.id), db, admin)
    shared = await cycles_router.create_cycle(CycleCreate(name="Shared", project_id=theirs.id), db, admin)
    unrelated = await cycles_router.create_cycle(CycleCreate(name="Unrelated", project_id=theirs.id), db, admin)
    await items.create_item(db, ItemCreate(project_id=mine.id, title="in their sprint", cycle_id=shared.id), admin)

    rows, _teams, _total = await directory.page(db, admin, project_id=mine.id, today=date.today())
    names = {row.name for row in rows}
    assert {"Own", "Shared"} <= names and "Unrelated" not in names, names
    assert unrelated.project_id == theirs.id
