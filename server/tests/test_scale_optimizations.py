"""Behavior parity and bounded-work regressions for the scale audit fixes."""
import uuid

import pytest
from sqlalchemy import and_, event, insert, or_, select, update

from test_item_visibility import db as _db, world as _world
from radd.modules.auth import authz
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.reporting import timeline
from radd.modules.realtime.hub import (
    ClientInfo, authorize_item_subscriptions, query_targets, validate_subscriptions,
)

db = _db
world = _world


@pytest.mark.parametrize("actor_name", ["world", "member", "reporter", "admin", "own_only"])
async def test_grouped_permissions_equal_per_project_predicates(db, world, actor_name):
    actor = world["actors"][actor_name]
    readable = await authz.readable_projects(db, actor)
    original = dict(readable)
    # Many projects with the same rules must add IDs, not row-guard subqueries.
    perms = readable[world["project"].id]
    readable.update({uuid.uuid4(): perms for _ in range(100)})
    relation_actor = await authz.relation_actor(db, actor)
    arms = []
    for pid, permissions in readable.items():
        clause = authz.relation_filter("item", authz.relations_held(
            permissions, authz.Permission.ITEM_READ), relation_actor)
        arms.append(WorkItem.project_id == pid if clause is None
                    else and_(WorkItem.project_id == pid, clause))
    expected = set(await db.scalars(select(WorkItem.id).where(or_(*arms))))
    grouped = await items.relation_read_clause(db, actor, readable)
    query = select(WorkItem.id).where(WorkItem.project_id.in_(readable))
    if grouped is not None:
        query = query.where(grouped)
    assert set(await db.scalars(query)) == expected
    if grouped is not None:
        original_clause = await items.relation_read_clause(db, actor, original)
        assert str(grouped).count("SELECT item_participants") == str(original_clause).count("SELECT item_participants")


async def test_large_id_batches_and_worker_paging_are_complete(db, world):
    project = world["project"]
    state_id = next(iter(world["rows"].values())).state.id
    inserted = [uuid.uuid4() for _ in range(1003)]
    await db.execute(insert(WorkItem), [dict(
        id=item_id, project_id=project.id, state_id=state_id, number=10000 + i,
        kind="issue", title="Batch boundary", priority="normal", estimate_points=2,
    ) for i, item_id in enumerate(inserted)])
    # Cross the actual PostgreSQL bind ceiling with absent IDs plus real rows
    # on both sides of chunk boundaries. Missing IDs and duplicates are legal.
    requested = [inserted[0], *[uuid.uuid4() for _ in range(65536)], *inserted, inserted[-1]]
    largest = 0

    def before(_conn, _cursor, _statement, parameters, _context, _many):
        nonlocal largest
        largest = max(largest, len(parameters))

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", before)
    try:
        assert set(await items.items_by_ids(db, requested)) == set(inserted)
        points = await items.estimate_points_by_ids(db, requested)
        assert points == dict.fromkeys(inserted, 2.0)
        histories = await timeline.build_item_timelines(db, requested)
        assert histories == {}  # these raw fixture rows intentionally have no events
    finally:
        event.remove(engine, "before_cursor_execute", before)
    assert largest < 1100
    batches = [batch async for batch in items.iter_project_items(db, project.id)]
    actual = [row.id for batch in batches for row in batch]
    expected = set(inserted) | {row.id for row in world["rows"].values()}
    assert set(actual) == expected
    assert len(actual) == len(expected)
    assert all(len(batch) <= 500 for batch in batches)
    refs = await items.item_refs(db, inserted)
    for item_id in [inserted[0], inserted[-1]]:
        assert refs[item_id] == await items.item_ref(db, item_id)


async def test_realtime_exact_interests_authorize_rows_and_keep_revocations_live(db, world):
    from radd.modules.items.enums import ItemVisibility

    member = world["actors"]["member"]
    public = str(world["rows"][ItemVisibility.PUBLIC].id)
    restricted = str(world["rows"][ItemVisibility.RESTRICTED].id)
    raw = [dict(id="public", entities=["item"], item_ids=[public]),
           dict(id="denied", entities=["item"], item_ids=[restricted])]
    subscriptions = await authorize_item_subscriptions(db, member, validate_subscriptions(raw, set()))
    assert subscriptions[0]["item_ids"] == [public]
    assert subscriptions[1]["item_ids"] is None
    # Denied/guessed identities receive coarse signals, never an existence oracle.
    class Event:
        entity_type = "item"
        event_type = "item.updated"
        payload = {"item": {"id": restricted}, "changes": [{"field": "priority"}]}
    info = ClientInfo(member.id, subscriptions)
    assert query_targets(info, Event()) == ["denied"]
    Event.payload["changes"] = [{"field": "visibility"}]
    assert query_targets(info, Event()) == ["public", "denied"]


async def test_sla_batches_keep_terminal_skip_and_emit_breaches_once(db, world, monkeypatch):
    from datetime import timedelta
    from radd.clock import utcnow
    from radd.modules.slas import engine, service as slas
    from radd.modules.slas.models import SlaItemState
    from radd.modules.slas.schemas import PolicyCreate

    pid = world["project"].id
    policy = await slas.create_policy(db, PolicyCreate(
        project_id=pid, name="Scale regression", resolution_minutes=1,
    ), actor_id=world["actors"]["admin"].id)
    ids = [item.id for item in world["rows"].values()]
    await db.execute(update(WorkItem).where(WorkItem.id.in_(ids)).values(
        created_at=utcnow() - timedelta(hours=1)))
    db.add(SlaItemState(item_id=ids[0], policy_id=policy.id, resolution_breached_at=utcnow()))
    await db.flush()
    original_batches = items.iter_project_items
    original_refs = items.item_refs
    referenced = []

    async def single_item_batches(session, project_id):
        async for batch in original_batches(session, project_id):
            for item in batch:
                yield [item]

    async def refs(session, requested):
        referenced.extend(requested)
        return await original_refs(session, requested)

    monkeypatch.setattr(items, "iter_project_items", single_item_batches)
    monkeypatch.setattr(items, "item_refs", refs)
    assert await engine._evaluate_project(db, pid, [policy]) == 2
    assert set(referenced) == set(ids[1:])
    referenced.clear()
    assert await engine._evaluate_project(db, pid, [policy]) == 0
    assert referenced == []
