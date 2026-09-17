"""The personal pin board is actor-scoped and retains completed issues."""

import uuid
import test_grouped_queue
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.workflow import service as workflow

setup = test_grouped_queue.setup


async def test_personal_starred_includes_completed_and_isolates_users(setup):
    db, actor, project = setup
    other = User(
        email=f"star-{uuid.uuid4()}@example.com",
        name="Other",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(other)
    await db.flush()
    issue = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Keep this completed issue"), actor=actor
    )
    done = next(
        state for state in await workflow.list_states(db, project.id) if state.category == "done"
    )
    (await db.get(WorkItem, issue.id)).state_id = done.id
    await db.flush()
    await items.star_item(db, issue.id, actor=actor)
    await items.star_item(db, issue.id, actor=actor)  # idempotent
    kwargs = dict(
        filters=ItemListFilters(),
        q="starred = true ORDER BY updated DESC",
        limit=50,
        offset=0,
        cursor_page={},
    )
    mine = await items.list_items(db, actor=actor, **kwargs)
    assert [row.id for row in mine] == [issue.id]
    assert mine[0].state.category == "done"
    assert not await items.list_items(db, actor=other, **kwargs)
    await items.star_item(db, issue.id, actor=other)
    await items.unstar_item(db, issue.id, actor=actor)
    assert not await items.list_items(db, actor=actor, **kwargs)
    assert [row.id for row in await items.list_items(db, actor=other, **kwargs)] == [issue.id]
