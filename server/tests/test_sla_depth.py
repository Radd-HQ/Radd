"""SLA depth (spec 63): first-match resolution against the DB, the list/board
batch compute (shape + permission filtering), and the weekly SLA report.

Live Postgres inside a rolled-back transaction, like tests/test_reporting.py.
The pure timer/first-match math lives in tests/test_sla.py.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.enums import Priority
from radd.modules.items.schemas import ItemCreate
from radd.modules.reporting import service as reporting
from radd.modules.slas import evaluation, service as slas
from radd.modules.slas.models import SlaItemState
from radd.modules.slas.schemas import PolicyCreate, PolicyUpdate
from radd.modules.slas.types import SlaKind
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
async def admin(db) -> User:
    user = User(
        email=f"sla-{uuid.uuid4().hex[:8]}@example.com",
        name="SLA Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db, run: str, key: str):
    return await projects_service.create_project(
        db, ProjectCreate(key=key, name=f"SLA {key}")
    )


async def _item(db, admin, project_id, priority=Priority.NORMAL):
    read = await items_service.create_item(
        db, ItemCreate(project_id=project_id, title=f"sla {priority}", priority=priority), admin
    )
    return (await items_service.items_by_ids(db, [read.id]))[read.id]


async def test_matched_policy_first_match_in_db(db, admin):
    run = uuid.uuid4().hex[:6]
    project = await _project(db, run, "SLD")
    p1 = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id,
            name="P1 fast",
            response_minutes=60,
            priorities=[Priority.BLOCKER],
            position=0,
        ),
        actor_id=admin.id,
    )
    standard = await slas.create_policy(
        db,
        PolicyCreate(project_id=project.id, name="Standard", response_minutes=480, position=1),
        actor_id=admin.id,
    )
    urgent = await _item(db, admin, project.id, Priority.BLOCKER)
    normal = await _item(db, admin, project.id)

    assert (await slas.matched_policy(db, urgent)).id == p1.id
    assert (await slas.matched_policy(db, normal)).id == standard.id
    # Reordering flips the winner for blockers (the catch-all now shadows P1).
    await slas.update_policy(db, standard.id, PolicyUpdate(position=0), actor_id=admin.id)
    await slas.update_policy(db, p1.id, PolicyUpdate(position=1), actor_id=admin.id)
    assert (await slas.matched_policy(db, urgent)).id == standard.id
    # A disabled policy never matches: normal items fall through P1's priority
    # filter and, with the catch-all off, end up governed by nothing.
    await slas.update_policy(db, standard.id, PolicyUpdate(enabled=False), actor_id=admin.id)
    assert (await slas.matched_policy(db, normal)) is None


async def test_business_window_validation(db, admin):
    run = uuid.uuid4().hex[:6]
    project = await _project(db, run, "SLW")
    with pytest.raises(ConflictError):
        await slas.create_policy(
            db,
            PolicyCreate(
                project_id=project.id,
                name="half a window",
                response_minutes=60,
                business_start_minute=540,
            ),
            actor_id=admin.id,
        )
    with pytest.raises(ConflictError):
        await slas.create_policy(
            db,
            PolicyCreate(
                project_id=project.id,
                name="inverted",
                response_minutes=60,
                business_start_minute=1050,
                business_end_minute=540,
            ),
            actor_id=admin.id,
        )


async def test_batch_sla_shape_and_permission_filtering(db, admin):
    run = uuid.uuid4().hex[:6]
    project_a = await _project(db, run, "SLA")
    project_b = await _project(db, run, "SLB")
    await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project_a.id,
            name="A standard",
            response_minutes=60,
            resolution_minutes=480,
        ),
        actor_id=admin.id,
    )
    await slas.create_policy(
        db,
        PolicyCreate(project_id=project_b.id, name="B standard", response_minutes=60),
        actor_id=admin.id,
    )
    mine = await _item(db, admin, project_a.id)
    theirs = await _item(db, admin, project_b.id)

    # Spec 86: any ACTIVE user reads every project; an INACTIVE one reads none.
    actor = User(
        email=f"sla-actor-{run}@example.com", name="Agent", instance_role=InstanceRole.MEMBER.value
    )
    inactive = User(
        email=f"sla-inactive-{run}@example.com",
        name="Gone",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add_all([actor, inactive])
    await db.flush()

    result = await evaluation.batch_sla(db, actor, [mine.id, theirs.id, uuid.uuid4()])
    # Unknown items are filtered out, not erred on; both projects are readable.
    assert set(result) == {mine.id, theirs.id}
    assert await evaluation.batch_sla(db, inactive, [mine.id, theirs.id]) == {}
    timers = result[mine.id]
    assert {t.kind for t in timers} == {SlaKind.RESPONSE, SlaKind.RESOLUTION}
    for timer in timers:
        assert timer.policy_name == "A standard"
        assert timer.met_at is None and timer.breached is False and timer.paused is False
        assert timer.due_at is not None and timer.remaining_seconds > 0


async def test_sla_report_smoke(db, admin):
    run = uuid.uuid4().hex[:6]
    project = await _project(db, run, "SLR")
    policy = await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id, name="Report", response_minutes=60, resolution_minutes=480
        ),
        actor_id=admin.id,
    )
    met = await _item(db, admin, project.id)
    late = await _item(db, admin, project.id)
    db.add(
        SlaItemState(
            item_id=met.id,
            policy_id=policy.id,
            response_met_at=met.created_at + timedelta(minutes=30),
            resolution_met_at=met.created_at + timedelta(hours=4),
        )
    )
    db.add(
        SlaItemState(
            item_id=late.id,
            policy_id=policy.id,
            response_breached_at=late.created_at + timedelta(minutes=61),
        )
    )
    await db.flush()

    # Spec 86: project_id=None is now truly global — scope to this test's project.
    buckets = (await reporting.sla_report(db, project.id, weeks=2)).buckets
    assert len(buckets) == 2
    assert sum(b.items for b in buckets) == 2
    assert sum(b.response_met for b in buckets) == 1
    assert sum(b.response_breached for b in buckets) == 1
    assert sum(b.resolution_met for b in buckets) == 1
    week = next(b for b in buckets if b.items)
    assert week.breach_rate == pytest.approx(0.5)
    assert week.avg_response_seconds == pytest.approx(30 * 60)
    assert week.avg_resolution_seconds == pytest.approx(4 * 3600)
    # Project scoping: an unrelated project sees an all-zero window.
    empty = (await reporting.sla_report(db, uuid.uuid4(), weeks=2)).buckets
    assert sum(b.items for b in empty) == 0
