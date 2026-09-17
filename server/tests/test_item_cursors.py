"""Hybrid continuation: real DB order, ties/nulls, mutations and scope guards."""

from datetime import date, timedelta

import pytest
from fastapi import Response
from sqlalchemy import delete

import test_grouped_queue

from radd.modules.items import service as items
from radd.modules.items.filters import ItemListFilters, FilterParseError
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.grouped import GroupPageRequest, grouped_items
from radd.modules.items.router import list_items as route_list

setup = test_grouped_queue.setup


async def seed(db, actor, project):
    first = await items.create_item(
        db, ItemCreate(project_id=project.id, title="first"), actor=actor
    )
    model = await db.get(WorkItem, first.id)
    model.rank = 1
    for n in range(2, 13):
        db.add(
            WorkItem(
                project_id=project.id,
                number=n,
                title=f"Row {n}",
                kind="issue",
                state_id=model.state_id,
                priority=["normal", "high", "low"][n % 3],
                rank=n,
                created_at=model.created_at,
                flagged=bool(n % 2),
                estimate_points=None if n % 3 == 0 else float(n % 4),
                target_date=None if n % 3 == 0 else date(2026, 9, 1) + timedelta(days=n % 4),
            )
        )
    await db.flush()
    return model


@pytest.mark.parametrize(
    "order",
    [
        "",
        "ORDER BY rank",
        "ORDER BY target ASC, priority DESC, number DESC",
        "ORDER BY target DESC",
        "ORDER BY points ASC",
        "ORDER BY points DESC",
        "ORDER BY category ASC, number ASC",
        "ORDER BY flagged DESC, created ASC",
    ],
)
async def test_cursor_matches_offset_order_with_ties_and_nulls(setup, order):
    db, actor, project = setup
    await seed(db, actor, project)
    kwargs = dict(actor=actor, filters=ItemListFilters(project_id=project.id), q=order, offset=0)
    expected = await items.list_items(db, **kwargs, limit=100)
    actual, after = [], None
    for _ in range(10):
        page = {}
        rows = await items.list_items(db, **kwargs, limit=3, cursor_page=page, after=after)
        actual.extend(i.id for i in rows)
        after = page["next"]
        if not after:
            break
    assert actual == [i.id for i in expected]
    assert len(actual) == len(set(actual)) == 12


async def test_boundary_survives_insert_before_and_deleted_anchor(setup):
    db, actor, project = setup
    model = await seed(db, actor, project)
    kwargs = dict(
        actor=actor,
        filters=ItemListFilters(project_id=project.id),
        q="ORDER BY number ASC",
        offset=0,
        limit=3,
    )
    page = {}
    first = await items.list_items(db, **kwargs, cursor_page=page)
    db.add(
        WorkItem(
            project_id=project.id,
            number=0,
            title="Inserted before",
            kind="issue",
            state_id=model.state_id,
            priority="normal",
            rank=0,
        )
    )
    await db.execute(delete(WorkItem).where(WorkItem.id == first[-1].id))
    await db.flush()
    next_page = await items.list_items(db, **kwargs, cursor_page={}, after=page["next"])
    assert [i.number for i in next_page] == [4, 5, 6]
    for changed in [
        dict(q="ORDER BY number DESC"),
        dict(filters=ItemListFilters()),
        dict(after="invalid"),
    ]:
        args = dict(kwargs, after=page["next"], cursor_page={}) | changed
        with pytest.raises(FilterParseError):
            await items.list_items(db, **args)
    with pytest.raises(FilterParseError):
        await items.list_items(db, **(kwargs | {"offset": 3}), cursor_page={})


async def test_board_cursor_keeps_full_totals_and_scope(setup):
    db, actor, project = setup
    model = await seed(db, actor, project)
    request = GroupPageRequest(
        project_id=project.id, axis="state", q="ORDER BY number ASC", item_limit=3, cursor_mode=True
    )
    first = await grouped_items(db, actor, request)
    cell = first.cells[0]
    assert cell.next_cursor
    await db.execute(delete(WorkItem).where(WorkItem.id == cell.items[-1].id))
    page = await grouped_items(
        db,
        actor,
        request.model_copy(update={"column_key": str(model.state_id), "after": cell.next_cursor}),
    )
    assert [i.number for i in page.cells[0].items] == [4, 5, 6]
    assert page.cells[0].total == 11
    with pytest.raises(FilterParseError):
        await grouped_items(
            db,
            actor,
            request.model_copy(
                update={
                    "column_key": str(model.state_id),
                    "after": cell.next_cursor,
                    "q": "ORDER BY number DESC",
                }
            ),
        )


async def test_http_contract_retains_array_and_adds_cursor_header(setup):
    db, actor, project = setup
    await seed(db, actor, project)
    response = Response()
    rows = await route_list(
        response,
        db,
        actor,
        project_id=project.id,
        q=None,
        state_id=None,
        category=None,
        kind=None,
        priority=None,
        parent_id=None,
        assignee_id=None,
        team_id=None,
        cycle_id=None,
        label=None,
        cf=None,
        archived=False,
        limit=3,
        offset=0,
        cursor_mode=True,
        after=None,
    )
    assert len(rows) == 3
    assert response.headers["X-Next-Cursor"]


async def test_large_sort_boundary_falls_back_without_unusable_url(setup):
    db, actor, project = setup
    await seed(db, actor, project)
    # WorkItem title length is bounded; custom field text is not.
    from radd.modules.items import cursors

    scope = cursors.scope_key(actor, ["large-sort"])
    token = cursors.encode(scope, ["x" * 10000], 50)
    assert len(token) < 4096
    assert cursors.decode(token, scope, 1) == (None, 50)


async def test_custom_numeric_cursor_preserves_decimal_and_null_order(setup):
    db, actor, project = setup
    await seed(db, actor, project)
    from sqlalchemy import select
    from radd.modules.fields import service as fields
    from radd.modules.fields.schemas import FieldDefinitionCreate
    from radd.modules.fields.types import FieldType

    await fields.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[project.id], key="cursor_score", name="Cursor score", type=FieldType.NUMBER
        ),
    )
    for i, row in enumerate(
        (await db.scalars(select(WorkItem).where(WorkItem.project_id == project.id))).all()
    ):
        row.custom_fields = {} if i % 3 == 0 else {"cursor_score": str(i / 10)}
    await db.flush()
    kwargs = dict(
        actor=actor,
        filters=ItemListFilters(project_id=project.id),
        q="ORDER BY cursor_score DESC",
        offset=0,
    )
    expected = await items.list_items(db, **kwargs, limit=100)
    seen, after = [], None
    for _ in range(10):
        page = {}
        rows = await items.list_items(db, **kwargs, limit=3, cursor_page=page, after=after)
        seen.extend(i.id for i in rows)
        after = page["next"]
        if not after:
            break
    assert seen == [i.id for i in expected]
