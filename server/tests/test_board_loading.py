"""Stable board metadata and row-only cursor reads preserve scope and totals."""

import pytest
from sqlalchemy import event
import test_grouped_queue
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.models import WorkItem
from radd.modules.items.grouped import GroupPageRequest, grouped_items
from radd.modules.items.filters import FilterParseError

setup = test_grouped_queue.setup


async def test_summary_and_cell_cursors_cover_complete_matrix_without_recount(setup):
    db, actor, project = setup
    for n in range(9):
        issue = await items.create_item(
            db,
            ItemCreate(
                project_id=project.id,
                title=f"card {n}",
                priority="high" if n % 2 else "normal",
                assignee_id=actor.id,
            ),
            actor=actor,
        )
        (await db.get(WorkItem, issue.id)).estimate_points = 3
    await db.flush()
    request = GroupPageRequest(
        project_id=project.id,
        axis="priority",
        lane="assignee",
        q="ORDER BY number ASC",
        item_limit=2,
    )
    original = await grouped_items(db, actor, request.model_copy(update={"item_limit": 50}))
    statements = []

    def collect(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(db.bind.sync_engine, "before_cursor_execute", collect)
    try:
        summary = await grouped_items(db, actor, request.model_copy(update={"summary_only": True}))
        assert summary.cells == []
        assert summary.column_totals == original.column_totals
        assert summary.column_points == original.column_points
        assert summary.lane_labels[str(actor.id)] == actor.name
        assert not any("row_number()" in sql for sql in statements)
        for cell in original.cells:
            statements.clear()
            seen, after = [], None
            for _ in range(5):
                page = await grouped_items(
                    db,
                    actor,
                    request.model_copy(
                        update={
                            "rows_only": True,
                            "cursor_mode": True,
                            "column_key": cell.column,
                            "lane_key": cell.lane,
                            "after": after,
                        }
                    ),
                )
                assert not page.column_totals  # Not misleading page-sized totals.
                assert page.cells[0].total is None
                seen.extend(i.id for i in page.cells[0].items)
                after = page.cells[0].next_cursor
                if not after:
                    break
                if len(seen) == 2:
                    with pytest.raises(FilterParseError):
                        await grouped_items(
                            db,
                            actor,
                            request.model_copy(
                                update={
                                    "rows_only": True,
                                    "cursor_mode": True,
                                    "column_key": cell.column,
                                    "lane_key": "__unassigned__",
                                    "after": after,
                                }
                            ),
                        )
            assert seen == [i.id for i in cell.items]
            assert not any(
                "GROUP BY anon_1.col" in sql or "row_number()" in sql for sql in statements
            )
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", collect)


async def test_rows_require_complete_cell_and_honor_hidden_columns(setup):
    db, actor, project = setup
    await items.create_item(
        db, ItemCreate(project_id=project.id, title="hidden", priority="high"), actor=actor
    )
    request = GroupPageRequest(
        project_id=project.id, axis="priority", rows_only=True, cursor_mode=True
    )
    with pytest.raises(FilterParseError):
        await grouped_items(db, actor, request)
    with pytest.raises(FilterParseError):
        await grouped_items(
            db, actor, request.model_copy(update={"column_key": "high", "lane": "assignee"})
        )
    page = await grouped_items(
        db, actor, request.model_copy(update={"column_key": "high", "hidden_columns": ["high"]})
    )
    assert not page.cells[0].items and not page.cells[0].next_cursor


async def test_directory_exceeds_old_group_limit_and_only_labels_matching_users(setup):
    import uuid
    from radd.modules.auth.models import User

    db, actor, project = setup
    seed = await items.create_item(db, ItemCreate(project_id=project.id, title="seed"), actor=actor)
    model = await db.get(WorkItem, seed.id)
    users = [User(name=f"Person {i}", email=f"board-{uuid.uuid4()}@example.com") for i in range(42)]
    db.add_all(users)
    await db.flush()
    for n, user in enumerate(users, 2):
        db.add(
            WorkItem(
                project_id=project.id,
                number=n,
                title=f"Work {n}",
                kind="issue",
                state_id=model.state_id,
                priority="normal" if n < 43 else "high",
                assignee_id=user.id,
            )
        )
    await db.flush()
    summary = await grouped_items(
        db,
        actor,
        GroupPageRequest(
            project_id=project.id, axis="assignee", summary_only=True, q="priority = normal"
        ),
    )
    assert len(summary.column_labels) == 42  # 41 people + the unassigned seed.
    assert summary.column_labels[str(users[40].id)] == "Person 40"
    assert str(users[41].id) not in summary.column_labels  # No matching visible issues.
    assert not summary.cells

    hidden = await grouped_items(
        db,
        actor,
        GroupPageRequest(
            project_id=project.id,
            axis="assignee",
            summary_only=True,
            q="priority = normal",
            hidden_columns=[str(users[0].id)],
        ),
    )
    assert str(users[0].id) not in hidden.column_totals
    assert hidden.column_labels[str(users[0].id)] == users[0].name
    assert sum(hidden.column_totals.values()) == sum(summary.column_totals.values()) - 1
