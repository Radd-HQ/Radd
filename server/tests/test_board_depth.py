"""Board depth (spec 76): WIP-limit validation on views, the epic-progress
rollup batch (descendants counted once, done by category, points/time sums,
visibility filtering, the 200-id cap), and issue-type description templates.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.types import InstanceRole, Permission
from radd.modules.items import rollup, service as items
from radd.modules.items.enums import ItemKind
from radd.modules.items.schemas import ItemRollupRequest, ROLLUP_MAX_ITEMS, ItemCreate
from radd.modules.itemtypes import service as itemtypes
from radd.modules.itemtypes.schemas import IssueTypeCreate, IssueTypeUpdate
from radd.modules.timelogging.models import ItemEstimate, Worklog
from radd.modules.views import service as views_service
from radd.modules.views.schemas import ViewCreate, ViewUpdate
from radd.modules.views.types import ViewType
from radd.modules.workflow import service as workflow
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


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"bd-{uuid.uuid4().hex[:8]}@example.com",
        name="Board Depth Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project_with_states(db, key_prefix="BD"):
    project = await projects_service.create_project(
        db,
        ProjectCreate(
            key=f"{key_prefix}{uuid.uuid4().hex[:4].upper()}",
            name="P",
        ),
    )
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    return project, states


# --- list columns (views, spec 108) ---


async def test_view_columns_round_trip_dedupe_and_clear(db, actor):
    project, _ = await _project_with_states(db)
    created = await views_service.create_view(
        db,
        ViewCreate(
            project_id=project.id,
            name="Table",
            view_type=ViewType.LIST,
            columns=["state", "assignee", " state ", "cf.site", ""],
        ),
        actor=actor,
    )
    # Trimmed, deduped (order kept), empties dropped.
    assert created.columns == ["state", "assignee", "cf.site"]

    updated = await views_service.update_view(
        db, created.id, ViewUpdate(columns=["priority", "state"]), actor
    )
    assert updated.columns == ["priority", "state"]

    # Explicit null = back to the type's defaults (client-side sets).
    cleared = await views_service.update_view(
        db, created.id, ViewUpdate(columns=None), actor
    )
    assert cleared.columns is None

    # Omitted = unchanged.
    await views_service.update_view(db, created.id, ViewUpdate(columns=["labels"]), actor)
    renamed = await views_service.update_view(db, created.id, ViewUpdate(name="T2"), actor)
    assert renamed.columns == ["labels"]


# --- WIP limits (views) ---


async def test_wip_limits_validation_and_round_trip(db, actor):
    project, states = await _project_with_states(db)

    # Non-positive limits are a shape error — pydantic rejects them (422).
    with pytest.raises(ValidationError):
        ViewCreate(
            name="Bad",
            view_type=ViewType.BOARD,
            wip_limits={states["Todo"].id: 0},
        )

    # Project-scoped views must key limits by that project's states -> 409.
    with pytest.raises(ConflictError):
        await views_service.create_view(
            db,
            ViewCreate(
                project_id=project.id,
                name="Unknown state",
                view_type=ViewType.BOARD,
                wip_limits={uuid.uuid4(): 3},
            ),
            actor=actor,
        )

    created = await views_service.create_view(
        db,
        ViewCreate(
            project_id=project.id,
            name="Board",
            view_type=ViewType.BOARD,
            wip_limits={states["Todo"].id: 3, states["In Progress"].id: 2},
        ),
        actor=actor,
    )
    assert created.wip_limits == {states["Todo"].id: 3, states["In Progress"].id: 2}

    # PATCH round-trip: unrelated updates leave limits alone…
    renamed = await views_service.update_view(
        db, created.id, ViewUpdate(name="Renamed"), actor=actor
    )
    assert renamed.wip_limits == created.wip_limits
    # …a set PATCH must still validate against the project's states…
    with pytest.raises(ConflictError):
        await views_service.update_view(
            db, created.id, ViewUpdate(wip_limits={uuid.uuid4(): 1}), actor=actor
        )
    # …and an explicit null clears (model_fields_set idiom).
    cleared = await views_service.update_view(
        db, created.id, ViewUpdate(wip_limits=None), actor=actor
    )
    assert cleared.wip_limits is None


async def test_wip_limits_all_projects_accepts_any_uuid(db, actor):
    foreign = uuid.uuid4()
    created = await views_service.create_view(
        db,
        ViewCreate(
            name="Spanning",
            view_type=ViewType.BOARD,
            wip_limits={foreign: 5},
        ),
        actor=actor,
    )
    assert created.wip_limits == {foreign: 5}


# --- Epic rollup (items) ---


async def _epic_tree(db, actor, project, states):
    """epic ← [done issue (3p), in-progress issue (2p)]; the done issue carries
    a canceled-category subtask (1p) — the nesting/count-once probe."""
    epic = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Epic", kind=ItemKind.EPIC), actor
    )
    done_issue = await items.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            title="Done child",
            parent_id=epic.id,
            state_id=states["Done"].id,
            estimate_points=3,
        ),
        actor,
    )
    await items.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            title="Active child",
            parent_id=epic.id,
            state_id=states["In Progress"].id,
            estimate_points=2,
        ),
        actor,
    )
    subtask = await items.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            title="Nested subtask",
            kind=ItemKind.SUBTASK,
            parent_id=done_issue.id,
            state_id=states["Canceled"].id,
            estimate_points=1,
        ),
        actor,
    )
    return epic, done_issue, subtask


async def test_rollup_counts_points_and_time(db, actor):
    project, states = await _project_with_states(db)
    epic, done_issue, subtask = await _epic_tree(db, actor, project, states)
    # Time rides the timelogging tables (module installed in tests).
    db.add(ItemEstimate(item_id=done_issue.id, original_estimate_seconds=7200))
    db.add(ItemEstimate(item_id=subtask.id, original_estimate_seconds=1800))
    db.add(
        Worklog(
            item_id=subtask.id,
            author_id=actor.id,
            worked_on=date(2026, 7, 20),
            time_spent_seconds=600,
        )
    )
    db.add(
        Worklog(
            item_id=subtask.id,
            author_id=actor.id,
            worked_on=date(2026, 7, 21),
            time_spent_seconds=300,
        )
    )
    await db.flush()

    result = await rollup.rollup_items(db, actor, [epic.id, done_issue.id, epic.id])

    top = result[epic.id]
    # Grandchild counted ONCE; done = done + canceled categories.
    assert (top.total, top.done, top.in_progress) == (3, 2, 1)
    assert (top.points_total, top.points_done) == (6, 4)
    assert (top.estimate_seconds, top.logged_seconds) == (9000, 900)
    # The mid-level issue rolls up only its own subtree.
    mid = result[done_issue.id]
    assert (mid.total, mid.done, mid.in_progress) == (1, 1, 0)
    assert (mid.points_total, mid.points_done) == (1, 1)
    assert (mid.estimate_seconds, mid.logged_seconds) == (1800, 900)


async def test_rollup_visibility_filter_and_caps(db, actor):
    project, states = await _project_with_states(db)
    epic, _, _ = await _epic_tree(db, actor, project, states)
    # RADD-825: the floor is item.read@own — an active user with NO grants who
    # didn't report the epic sees an EMPTY rollup (the visibility filter, not
    # an error); a project read grant restores it; an INACTIVE user gets
    # nothing (and unknown ids are omitted, never errored).
    other = User(
        email=f"bd-out-{uuid.uuid4().hex[:8]}@example.com",
        name="Other",
        instance_role=InstanceRole.MEMBER.value,
    )
    inactive = User(
        email=f"bd-in-{uuid.uuid4().hex[:8]}@example.com",
        name="Inactive",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add_all([other, inactive])
    await db.flush()
    assert await rollup.rollup_items(db, other, [epic.id, uuid.uuid4()]) == {}
    role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"bd{uuid.uuid4().hex[:6]}", name="Reader",
            permissions=[Permission.ITEM_READ],
        ),
    )
    db.add(GlobalRoleGrant(project_id=project.id, user_id=other.id, role_id=role.id))
    await db.flush()
    # The per-actor permission map memoises per request/session; the first
    # rollup call above cached the pre-grant answer.
    db.info.pop(f"radd.project_permission_map:{other.id}", None)
    db.info.pop(f"radd.readable_projects:{other.id}", None)
    visible = await rollup.rollup_items(db, other, [epic.id, uuid.uuid4()])
    assert set(visible) == {epic.id}
    assert await rollup.rollup_items(db, inactive, [epic.id, uuid.uuid4()]) == {}
    # Readable roots always appear — zeros distinguish "no children".
    leaf_only = await rollup.rollup_items(db, actor, [epic.id])
    assert leaf_only[epic.id].total == 3
    # The batch cap is schema-enforced (422 at the boundary).
    with pytest.raises(ValidationError):
        ItemRollupRequest(item_ids=[uuid.uuid4() for _ in range(ROLLUP_MAX_ITEMS + 1)])


# --- Issue templates (itemtypes) ---


async def test_description_template_round_trip(db, actor):
    project, _ = await _project_with_states(db)
    created = await itemtypes.create_type(
        db,
        IssueTypeCreate(
            project_id=project.id,
            name=f"Regression {uuid.uuid4().hex[:6]}",  # default types already ship a Bug
            color="#ef4444",
            description_template="## Steps to reproduce\n\n1. ",
        ),
        actor_id=actor.id,
    )
    assert created.description_template == "## Steps to reproduce\n\n1. "

    # Unrelated PATCH leaves the template untouched (model_fields_set idiom).
    updated = await itemtypes.update_type(
        db, created.id, IssueTypeUpdate(color="#22c55e"), actor_id=actor.id
    )
    assert updated.description_template == "## Steps to reproduce\n\n1. "

    updated = await itemtypes.update_type(
        db,
        created.id,
        IssueTypeUpdate(description_template="## Expected\n\n## Actual"),
        actor_id=actor.id,
    )
    assert updated.description_template == "## Expected\n\n## Actual"

    # Explicit null clears back to "no template".
    cleared = await itemtypes.update_type(
        db, created.id, IssueTypeUpdate(description_template=None), actor_id=actor.id
    )
    assert cleared.description_template is None
