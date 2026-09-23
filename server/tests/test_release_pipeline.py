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
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.mcp import tools
from radd.modules.mcp.types import McpTool
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.releases import pipeline, service as releases_service
from radd.modules.releases.schemas import ReleaseCreate, ReleaseUpdate
from radd.modules.releases.types import ReleaseStatus
from radd.modules.reporting import service as reporting, timeline
from radd.modules.reporting.types import ReportInterval
from radd.exceptions import ConflictError
from radd.modules.workflow import service as workflow
from radd.modules.workflow import transitions
from radd.modules.workflow.schemas import StateCreate, StateUpdate, TransitionCreate, TransitionRule
from radd.modules.workflow.types import StateCategory, TransitionCheck

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


async def _configure(db, project, *, waiting: str = WAITING, shipped: str = SHIPPED):
    """The waiting state sits in the DONE category — that is the design decision
    the whole spec turns on. RADD-1285: shipping is an on-release transition
    waiting → shipped, not two settings."""
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
    by_name = {s.name: s for s in await workflow.list_states(db, project.id)}
    return await transitions.create_transition(db, TransitionCreate(
        project_id=project.id, from_state_id=by_name[waiting].id,
        to_state_id=by_name[shipped].id, on_release=True,
    ))


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


async def test_a_project_without_an_on_release_transition_is_untouched(db, project, admin):
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


async def test_renaming_the_waiting_state_keeps_the_pipeline(db, project, admin):
    """RADD-1285: the old settings held state NAMES, so a rename switched the
    pipeline off. A transition holds ids — rename away."""
    await _configure(db, project)
    item = await _item_in_waiting(db, project, admin)
    waiting = next(s for s in await workflow.list_states(db, project.id) if s.name == WAITING)
    await workflow.update_state(db, waiting.id, StateUpdate(name="Merged, not shipped"))
    assert await pipeline.waiting_state_id(db, project) == waiting.id
    release, moved = await pipeline.on_release_published(db, project, version="7.0.0")
    assert moved == 1
    assert (await items_service.get_item(db, item.id, admin)).release.version == "7.0.0"


async def test_on_release_needs_one_named_from_state(db, project, admin):
    """A release moves work OUT of a state, so "Any state" cannot ship; and one
    state cannot ship to two places."""
    row = await _configure(db, project)
    with pytest.raises(ConflictError):
        await transitions.create_transition(db, TransitionCreate(
            project_id=project.id, from_state_id=None, to_state_id=row.to_state_id, on_release=True))
    other = next(s for s in await workflow.list_states(db, project.id) if s.id not in (row.from_state_id, row.to_state_id))
    with pytest.raises(ConflictError):
        await transitions.create_transition(db, TransitionCreate(
            project_id=project.id, from_state_id=row.from_state_id, to_state_id=other.id, on_release=True))


async def test_requires_a_release_refuses_until_one_is_set_and_the_sweep_satisfies_it(db, project, admin):
    """The named check replaces the hand-built require_field(release, set): a
    person cannot move work into the shipped state without a release, and the
    sweep can, because it sets the release in the same patch."""
    row = await _configure(db, project)
    # A wildcard gate above it. The on-release row is an EXACT-from row, so it
    # governs Waiting → Done over this — which is why it carries the gate itself.
    await transitions.create_transition(db, TransitionCreate(
        project_id=project.id, from_state_id=None, to_state_id=row.to_state_id,
        rules=[TransitionRule(check=TransitionCheck.REQUIRE_RELEASE)], position=0))
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey, SettingScope
    await settings_service.set_value(db, SettingKey.WORKFLOW_TRANSITION_MODE,
                                     scope=SettingScope.PROJECT, scope_id=project.id, value="guards")
    item = await _item_in_waiting(db, project, admin)
    # Asked the way the state picker asks (a refused update would leave its
    # half-applied state in this test's session; a real request rolls back).
    model = await items_service.require_item(db, item.id)
    allowed = await transitions.allowed_transitions(db, project, model)
    target = next(t for t in allowed.targets if t.state_id == row.to_state_id)
    assert not target.allowed and target.failures == ["a release is required"]
    _release, moved = await pipeline.on_release_published(db, project, version="6.0.0")
    assert moved == 1


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


# --- every write path sweeps (RADD-1007) ---


async def test_marking_a_version_released_sweeps(db, project, admin):
    """The browser's "Mark released" is a PATCH; it must ship what is waiting,
    exactly like a published connector release — one rule, one home."""
    await _configure(db, project)
    item = await _item_in_waiting(db, project, admin)
    planned = await releases_service.create_release(
        db, ReleaseCreate(project_id=project.id, name="x", version="3.0.0")
    )
    assert (await items_service.get_item(db, item.id, admin)).release is None

    release, moved = await pipeline.update_release(
        db, planned.id, ReleaseUpdate(status=ReleaseStatus.RELEASED), actor_id=admin.id
    )
    assert moved == 1 and release.released_at is not None
    assert (await items_service.get_item(db, item.id, admin)).release.version == "3.0.0"

    # Re-saving an already-released version (an edit to its notes) is not a
    # second sweep — that is the explicit sweep's job.
    await _item_in_waiting(db, project, admin, "later")
    _release, again = await pipeline.update_release(
        db, planned.id, ReleaseUpdate(description="notes"), actor_id=admin.id
    )
    assert again == 0


async def test_a_version_created_as_released_sweeps(db, project, admin):
    await _configure(db, project)
    await _item_in_waiting(db, project, admin)
    _release, moved = await pipeline.create_release(
        db,
        ReleaseCreate(
            project_id=project.id, name="x", version="3.1.0", status=ReleaseStatus.RELEASED
        ),
        actor_id=admin.id,
    )
    assert moved == 1
    _planned, none = await pipeline.create_release(
        db, ReleaseCreate(project_id=project.id, name="x", version="3.2.0"), actor_id=admin.id
    )
    assert none == 0


async def test_release_notes_survive_the_pipeline_whole(db, project, admin):
    """RADD-907: the record used to keep 2000 characters of a 20 KB changelog."""
    notes = "\n".join(f"- RADD-{n}: an entry long enough to matter" for n in range(400))
    assert len(notes) > 2000
    release, _ = await pipeline.on_release_published(db, project, version="4.0.0", notes=notes)
    assert release.description == notes


# --- the MCP surface (RADD-908) ---


async def test_release_notes_are_readable_and_writable_over_mcp(db, project, admin):
    await _configure(db, project)
    await _item_in_waiting(db, project, admin)
    published, _ = await pipeline.on_release_published(
        db, project, version="5.0.0", notes="generated changelog"
    )

    listed = await tools.call_tool(
        db, admin, McpTool.LIST_RELEASES.value, {"project_key": project.key}
    )
    assert [r["version"] for r in listed] == ["5.0.0"] and "description" not in listed[0]

    read = await tools.call_tool(
        db, admin, McpTool.GET_RELEASE.value, {"project_key": project.key, "version": "5.0.0"}
    )
    assert read["description"] == "generated changelog" and read["released_at"]

    amended = await tools.call_tool(
        db,
        admin,
        McpTool.UPDATE_RELEASE.value,
        {
            "project_key": project.key,
            "version": "5.0.0",
            "description": "## The wave\n\ngenerated changelog",
            "name": "Radd 5",
        },
    )
    assert amended["items_shipped"] == 0  # already released: no second sweep
    stored = await releases_service.get_release(db, published.id)
    assert stored.description.startswith("## The wave") and stored.name == "Radd 5"

    with pytest.raises(NotFoundError):
        await tools.call_tool(
            db, admin, McpTool.GET_RELEASE.value, {"project_key": project.key, "version": "nope"}
        )


async def test_marking_released_over_mcp_sweeps(db, project, admin):
    await _configure(db, project)
    await _item_in_waiting(db, project, admin)
    await tools.call_tool(
        db, admin, McpTool.CREATE_RELEASE.value, {"project_key": project.key, "version": "6.0.0"}
    )
    shipped = await tools.call_tool(
        db,
        admin,
        McpTool.UPDATE_RELEASE.value,
        {"project_key": project.key, "version": "6.0.0", "status": ReleaseStatus.RELEASED.value},
    )
    assert shipped["status"] == ReleaseStatus.RELEASED.value and shipped["items_shipped"] == 1
