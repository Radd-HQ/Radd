"""Two people on one item (RADD-1539).

Nothing in the suite had ever put two writers on one row. These do, with real
transactions (they commit, and clean up after themselves): the first writer
holds the item, the second starts while it does, and the test asserts both that
the second WAITED and what the row holds once both have committed.

The rule the tests pin down:

- different fields: both edits survive (including two keys of `custom_fields`,
  which is one JSONB column and used to be written back whole);
- the description, with the version the edit started from: the stale save is
  refused with the current text. Without a version it is last-write-wins — the
  wire contract imports, automations and MCP callers already rely on;
- two transitions: the second is judged from the state the first left.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select

from radd.db import SessionLocal
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.schemas import FieldDefinitionCreate
from radd.modules.fields.types import FieldType
from radd.modules.items import service as items
from radd.modules.items.filters import DescriptionConflict
from radd.modules.items.models import ItemTransition, WorkItem
from radd.modules.items.schemas import ItemCreate, ItemRankUpdate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory

from _factories import make_user

#: Long enough for the second writer to reach the row lock and stop there.
_SETTLE = 0.3


@pytest.fixture
async def world():
    """A committed admin, project and two text fields; removed afterwards."""
    tag = uuid.uuid4().hex[:6]
    async with SessionLocal() as session:
        admin = await make_user(session, role=InstanceRole.ADMIN, name="Concurrent")
        project = await projects_service.create_project(
            session, ProjectCreate(key=f"CC{tag[:5].upper()}", name=f"Concurrency {tag}")
        )
        keys = []
        for name in ("shot", "vendor"):
            definition = await fields.create_field(
                session,
                FieldDefinitionCreate(key=f"{name}_{tag}", name=name, type=FieldType.TEXT),
                actor_id=admin.id,
            )
            keys.append(definition.key)
        item = await items.create_item(
            session, ItemCreate(project_id=project.id, title="shared", description="v0"), admin
        )
        await session.commit()
    try:
        yield admin, project, item.id, keys
    finally:
        async with SessionLocal() as session:
            await projects_service.delete_project(
                session, await projects_service.get_project(session, project.id)
            )
            await session.execute(delete(FieldDefinition).where(FieldDefinition.key.in_(keys)))
            await session.execute(delete(User).where(User.id == admin.id))
            await session.commit()


async def _race(first, second):
    """Run `first` and leave it uncommitted, start `second`, prove it is waiting
    on the row, then let both finish. Returns the second writer's outcome (its
    result, or the exception it raised)."""
    async with SessionLocal() as one, SessionLocal() as two:
        await first(one)

        async def late():
            try:
                result = await second(two)
                await two.commit()
                return result
            except Exception as error:  # noqa: BLE001 — the outcome under test
                await two.rollback()
                return error

        waiting = asyncio.create_task(late())
        await asyncio.sleep(_SETTLE)
        assert not waiting.done(), "the second writer did not wait for the first"
        await one.commit()
        return await waiting


async def _row(item_id) -> WorkItem:
    async with SessionLocal() as session:
        return await session.get(WorkItem, item_id)


async def test_edits_to_different_custom_fields_both_survive(world):
    admin, _project, item_id, (shot, vendor) = world
    await _race(
        lambda s: items.update_item(s, item_id, ItemUpdate(custom_fields={shot: "sh010"}), admin),
        lambda s: items.update_item(s, item_id, ItemUpdate(custom_fields={vendor: "acme"}), admin),
    )
    row = await _row(item_id)
    # One JSONB column: the second writer used to merge into the document it had
    # read BEFORE the first committed, and write that back — dropping `shot`.
    assert row.custom_fields.get(shot) == "sh010" and row.custom_fields.get(vendor) == "acme"


async def test_edits_to_different_builtin_fields_both_survive(world):
    admin, _project, item_id, _keys = world
    await _race(
        lambda s: items.update_item(s, item_id, ItemUpdate(title="renamed"), admin),
        lambda s: items.update_item(s, item_id, ItemUpdate(estimate_points=5), admin),
    )
    row = await _row(item_id)
    assert row.title == "renamed" and float(row.estimate_points) == 5.0


async def test_a_stale_description_save_is_refused_with_the_current_text(world):
    admin, _project, item_id, _keys = world
    started_from = (await _row(item_id)).description_version
    outcome = await _race(
        lambda s: items.update_item(
            s, item_id, ItemUpdate(description="first", description_version=started_from), admin
        ),
        lambda s: items.update_item(
            s, item_id, ItemUpdate(description="second", description_version=started_from), admin
        ),
    )
    assert isinstance(outcome, DescriptionConflict)
    assert outcome.current == "first" and outcome.version == started_from + 1
    row = await _row(item_id)
    assert row.description == "first" and row.description_version == started_from + 1


async def test_a_description_save_without_a_version_is_last_write_wins(world):
    """The chosen rule for callers that do not say what they edited from."""
    admin, _project, item_id, _keys = world
    await _race(
        lambda s: items.update_item(s, item_id, ItemUpdate(description="first"), admin),
        lambda s: items.update_item(s, item_id, ItemUpdate(description="second"), admin),
    )
    row = await _row(item_id)
    assert row.description == "second" and row.description_version == 2


async def test_two_transitions_are_judged_one_after_the_other(world):
    admin, project, item_id, _keys = world
    async with SessionLocal() as session:
        states = await workflow.list_states(session, project.id)
    started = next(s for s in states if s.category == StateCategory.IN_PROGRESS.value)
    done = next(s for s in states if s.category == StateCategory.DONE.value)
    await _race(
        lambda s: items.update_item(s, item_id, ItemUpdate(state_id=started.id), admin),
        lambda s: items.update_item(s, item_id, ItemUpdate(state_id=done.id), admin),
    )
    async with SessionLocal() as session:
        history = (
            await session.execute(
                select(ItemTransition.from_state_id, ItemTransition.state_id)
                .where(ItemTransition.item_id == item_id)
                .order_by(ItemTransition.id)
            )
        ).all()
    # A chain, not a fork: the second move left the state the first one entered.
    # Unlocked, both were validated — and recorded — as leaving the original state.
    assert [(row.from_state_id, row.state_id) for row in history[1:]] == [
        (history[0].state_id, started.id),
        (started.id, done.id),
    ]


async def test_a_transition_racing_an_edit_keeps_both(world):
    admin, project, item_id, _keys = world
    async with SessionLocal() as session:
        states = await workflow.list_states(session, project.id)
    done = next(s for s in states if s.category == StateCategory.DONE.value)
    await _race(
        lambda s: items.update_item(s, item_id, ItemUpdate(state_id=done.id), admin),
        lambda s: items.update_item(s, item_id, ItemUpdate(title="edited meanwhile"), admin),
    )
    row = await _row(item_id)
    assert row.state_id == done.id and row.title == "edited meanwhile"


async def test_a_collapsed_rank_gap_respaces_the_neighbourhood_not_the_table(world, monkeypatch):
    """Dropping a card between two whose midpoint is no longer a distinct float
    used to renumber every item on the instance inside the request."""
    admin, project, _item_id, _keys = world
    renumbered = []

    async def never(session):
        renumbered.append(True)

    monkeypatch.setattr(items.core, "_rebalance_ranks", never)
    async with SessionLocal() as session:
        made = [
            await items.create_item(
                session, ItemCreate(project_id=project.id, title=f"card {n}"), admin
            )
            for n in range(4)
        ]
        above, below, moving, bystander = (row.id for row in made)
        rows = {row.id: row for row in (await session.execute(select(WorkItem))).scalars()}
        # Adjacent floats: no rank fits between them. A row far away must not move.
        rows[above].rank = 7_000_000.0
        rows[below].rank = 7_000_000.000000001
        rows[bystander].rank = -9_000_000.0
        await session.commit()

        await items.reorder_item(
            session, moving, ItemRankUpdate(after_id=above, before_id=below), admin
        )
        await session.commit()
    ranks = {}
    async with SessionLocal() as session:
        for row in (await session.execute(select(WorkItem.id, WorkItem.rank))).all():
            ranks[row.id] = row.rank
    assert ranks[above] < ranks[moving] < ranks[below]
    assert ranks[bystander] == -9_000_000.0
    assert not renumbered
