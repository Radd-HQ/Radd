"""Spec 112: work finishes once, ships later.

The claim under test is that the two questions stay separate — throughput counts
the day the work was FINISHED (entry into the waiting state, which is a
done-category state), and the release only records when it shipped. Plus the
sweep's own invariants: idempotent, never repoints an already-shipped item, and
inert on a project that has not opted in.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as app_settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.releases import pipeline, service as releases_service
from radd.modules.releases.schemas import ReleaseCreate
from radd.modules.reporting import service as reporting, timeline
from radd.modules.reporting.types import ReportInterval
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.workflow import service as workflow
from radd.modules.workflow.schemas import StateCreate
from radd.modules.workflow.types import StateCategory

WAITING = "Waiting for release"
SHIPPED = "Done"


@pytest.fixture
async def db():
    engine = create_async_engine(app_settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"rel-{uuid.uuid4().hex[:8]}@example.com",
        name="Release admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"RP{uuid.uuid4().hex[:4].upper()}", name="Release pipeline")
    )


async def _configure(db, project, *, waiting: str = WAITING, shipped: str = SHIPPED) -> None:
    """The waiting state sits in the DONE category — that is the design decision
    the whole spec turns on."""
    states = await workflow.list_states(db, project.id)
    if waiting and not any(s.name == waiting for s in states):
        await workflow.create_state(
            db,
            StateCreate(
                project_id=project.id,
                name=waiting,
                category=StateCategory.DONE,
                position=len(states) + 1,
            ),
        )
    for key, value in (
        (SettingKey.RELEASE_WAITING_STATE, waiting),
        (SettingKey.RELEASE_SHIPPED_STATE, shipped),
    ):
        await settings_service.set_value(
            db, key, scope=SettingScope.PROJECT, scope_id=project.id, value=value
        )


async def _item_in_waiting(db, project, admin, title="work"):
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title=title), admin
    )
    await items_service.update_item(
        db, item.id, ItemUpdate(state_id=states[WAITING].id), admin
    )
    return item


# --- the sweep ---


async def test_publishing_records_the_release_and_ships_what_was_waiting(db, project, admin):
    await _configure(db, project)
    first = await _item_in_waiting(db, project, admin, "first")
    second = await _item_in_waiting(db, project, admin, "second")

    release, moved = await pipeline.on_release_published(
        db, project, version="1.2.0", name="Radd 1.2.0", notes="notes"
    )
    assert moved == 2 and release.version == "1.2.0"

    states = {s.id: s.name for s in await workflow.list_states(db, project.id)}
    for item_id in (first.id, second.id):
        read = await items_service.get_item(db, item_id, admin)
        assert states[read.state.id] == SHIPPED
        assert read.release is not None and read.release.version == "1.2.0"


async def test_the_sweep_is_idempotent(db, project, admin):
    await _configure(db, project)
    await _item_in_waiting(db, project, admin)

    release, first = await pipeline.on_release_published(db, project, version="1.3.0")
    assert first == 1
    _again, second = await pipeline.on_release_published(db, project, version="1.3.0")
    assert second == 0  # nothing is waiting any more


async def test_a_republished_tag_reuses_its_version_row(db, project, admin):
    await _configure(db, project)
    first, _ = await pipeline.on_release_published(db, project, version="1.4.0")
    again, _ = await pipeline.on_release_published(db, project, version="1.4.0")
    assert first.id == again.id
    versions = [r.version for r in await releases_service.list_releases(db, project.id)]
    assert versions.count("1.4.0") == 1


async def test_an_already_shipped_item_keeps_its_original_release(db, project, admin):
    await _configure(db, project)
    item = await _item_in_waiting(db, project, admin)
    await pipeline.on_release_published(db, project, version="1.5.0")

    await pipeline.on_release_published(db, project, version="1.6.0")
    read = await items_service.get_item(db, item.id, admin)
    assert read.release.version == "1.5.0"  # not repointed by a later release


async def test_a_project_without_the_settings_is_untouched(db, project, admin):
    """No opt-in, no behaviour. The pipeline must not act on projects that never
    asked for it."""
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="untouched"), admin
    )
    target = next(s for s in states.values() if s.category == StateCategory.TODO.value)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=target.id), admin)

    release = await releases_service.create_release(
        db, ReleaseCreate(project_id=project.id, name="x", version="9.9.9")
    )
    assert await pipeline.sweep(db, project, release) == 0
    read = await items_service.get_item(db, item.id, admin)
    assert read.state.id == target.id and read.release is None


async def test_a_state_named_in_settings_but_missing_is_survivable(db, project, admin):
    """A renamed state is a settings problem; it must not raise."""
    await _configure(db, project, waiting="Nowhere")
    release = await releases_service.create_release(
        db, ReleaseCreate(project_id=project.id, name="x", version="8.8.8")
    )
    assert await pipeline.sweep(db, project, release) == 0


# --- what the reports say ---


async def test_throughput_counts_the_finish_not_the_ship(db, project, admin):
    """The reason the waiting state is in the DONE category: entering it is when
    the work was finished, and the later move to Done must not count it twice."""
    await _configure(db, project)
    item = await _item_in_waiting(db, project, admin)

    tl = (await timeline.build_item_timelines(db, [item.id]))[item.id]
    assert len(tl.done_entries) == 1  # entering "Waiting for release" IS a completion

    await pipeline.on_release_published(db, project, version="2.0.0")
    tl = (await timeline.build_item_timelines(db, [item.id]))[item.id]
    assert len(tl.done_entries) == 1  # ...and shipping does not add a second

    rows = await reporting.throughput(
        db, project.id, date.today() - timedelta(days=1), date.today(), ReportInterval.DAY
    )
    assert sum(row.count for row in rows) == 1
