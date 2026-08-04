"""Itemless (general) worklogs — spec 59 core invariants: scope anchoring,
category enforcement, and the timesheet including both kinds of rows."""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.timelogging import categories, service as timelog, timesheet
from radd.modules.timelogging.schemas import GeneralWorklogCreate, WorklogUpdate
from radd.modules.timelogging.service import get_worklog
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"gw-{uuid.uuid4().hex[:8]}@example.com",
        name="General Worklogger",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _category(db, actor):
    # Default categories are global and seeded on app startup — which these
    # tests don't do — so ensure them here (idempotent) before picking one.
    await categories.ensure_default_categories(db)
    cats = await categories.list_categories(db)
    return cats[0]


def test_general_worklog_anchor_is_optional_at_the_schema():
    # Spec 86: no workspace anchor exists — an itemless entry needs only a
    # category; the project anchor stays optional.
    data = GeneralWorklogCreate(category_id=uuid.uuid4(), time_spent="1h")
    assert data.project_id is None


def test_general_worklog_requires_category():
    with pytest.raises(ValidationError):
        GeneralWorklogCreate(time_spent="1h")  # type: ignore[call-arg]


async def test_itemless_worklog_and_timesheet(db, actor):
    # A timesheet is built over the instance's projects; with none at all it short
    # -circuits to empty (build() line ~39), so itemless rows need at least one
    # project to exist to surface. Every real deployment has one — create one here
    # rather than lean on the DB already being populated (the wipe exposed this).
    await projects_service.create_project(
        db, ProjectCreate(key=f"GW{uuid.uuid4().hex[:4].upper()}", name="Timesheet host")
    )
    category = await _category(db, actor)
    read = await timelog.create_general_worklog(
        db,
        GeneralWorklogCreate(
            category_id=category.id,
            time_spent="2h",
            note="standup + planning",
        ),
        actor.id,
        today=date(2026, 7, 22),
    )
    assert read.item_id is None and read.project_id is None
    assert read.category is not None and read.category.id == category.id
    assert read.time_spent_seconds == 7200

    # Global timesheet scoped to this actor (isolates the freshly-created rows
    # from other users' committed worklogs).
    sheet = await timesheet.build(
        db, date(2026, 7, 20), date(2026, 7, 26), actor=actor, user_ids={actor.id}
    )
    assert len(sheet.entries) == 1
    entry = sheet.entries[0]
    assert entry.item is None and entry.project_key is None
    assert entry.category is not None and entry.category.name == category.name
    assert sheet.total_seconds == 7200


async def test_project_anchored_worklog_filters_and_category_lock(db, actor):
    category = await _category(db, actor)
    key = f"GX{uuid.uuid4().hex[:4].upper()}"
    project = await projects_service.create_project(
        db, ProjectCreate(key=key, name="Proj")
    )
    from radd.modules.timelogging import enablement

    await enablement.set_enabled(db, project.id, True)
    read = await timelog.create_general_worklog(
        db,
        GeneralWorklogCreate(project_id=project.id, category_id=category.id, time_spent="30m"),
        actor.id,
        today=date(2026, 7, 22),
    )
    assert read.project_id == project.id

    # Project filter keeps its own itemless rows…
    sheet = await timesheet.build(
        db, date(2026, 7, 20), date(2026, 7, 26), actor=actor, project_id=project.id
    )
    assert [e.project_key for e in sheet.entries] == [key]
    # …and the category can be swapped but never cleared on an itemless entry.
    worklog = await get_worklog(db, read.id)
    with pytest.raises(ConflictError):
        await timelog.update_worklog(
            db, worklog, WorklogUpdate(category_id=None), actor.id
        )
