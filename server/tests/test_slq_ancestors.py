"""SLQ ancestor fields (spec 83): bare `epic`/`parent` + `epic.*`/`parent.*`.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist. Queries drive through items.list_items q=
like the other SLQ tests, so compile AND execution are both proven.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import bulk, service as items
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemBulkMove, ItemCreate, ItemUpdate
from radd.modules.items.slq import SlqError, compile_query, parse
from radd.modules.items.slq.suggest import suggestions_for
from radd.modules.items.slq.suggest_values import SuggestScope
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
        email=f"anc-{uuid.uuid4().hex[:8]}@example.com",
        name="Ancestor Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project_with_states(db, key_prefix="ANC"):
    project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"{key_prefix}{uuid.uuid4().hex[:4].upper()}", name="P"),
    )
    states = {s.name: s for s in await workflow.list_states(db, project.id)}
    return project, states


async def _titles(db, actor, project, q):
    rows = await items.list_items(
        db,
        actor=actor,
        filters=ItemListFilters(project_id=project.id),
        q=q,
        limit=50,
        offset=0,
    )
    return {r.title for r in rows}


async def _ladder(db, actor, project, states):
    """epic (In Progress, blocker, assigned to actor) <- issue <- subtask,
    a second unassigned epic <- issue2, and a parentless `loner` issue."""
    epic = await items.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            title="epic",
            kind=ItemKind.EPIC,
            state_id=states["In Progress"].id,
            priority=Priority.BLOCKER,
            assignee_id=actor.id,
        ),
        actor,
    )
    issue = await items.create_item(
        db, ItemCreate(project_id=project.id, title="issue", parent_id=epic.id), actor
    )
    subtask = await items.create_item(
        db,
        ItemCreate(
            project_id=project.id, title="subtask", kind=ItemKind.SUBTASK, parent_id=issue.id
        ),
        actor,
    )
    epic2 = await items.create_item(
        db, ItemCreate(project_id=project.id, title="epic2", kind=ItemKind.EPIC), actor
    )
    issue2 = await items.create_item(
        db, ItemCreate(project_id=project.id, title="issue2", parent_id=epic2.id), actor
    )
    loner = await items.create_item(db, ItemCreate(project_id=project.id, title="loner"), actor)
    return epic, issue, subtask, epic2, issue2, loner


# --- epic.* traversal: SELF for epics, parent for issues, grandparent for subtasks ---


async def test_epic_subfields_match_the_epic_itself_and_its_descendants(db, actor):
    project, states = await _project_with_states(db)
    await _ladder(db, actor, project, states)

    # The epic matches its OWN attributes (spec 83 amendment); the issue matches
    # via its parent, the subtask via its grandparent.
    tree = {"epic", "issue", "subtask"}
    assert await _titles(db, actor, project, "epic.state = 'In Progress'") == tree
    # state names are case-insensitive (spec 83).
    assert await _titles(db, actor, project, "epic.state = 'in progress'") == tree
    category = states["In Progress"].category
    assert await _titles(db, actor, project, f"epic.category = {category}") == tree
    assert await _titles(db, actor, project, "epic.priority = blocker") == tree
    assert await _titles(db, actor, project, "epic.assignee = me") == tree
    assert await _titles(db, actor, project, f"epic.assignee = {actor.email}") == tree
    # IS EMPTY is a POSITIVE predicate over the epic row, so the epicless
    # `loner` is out; the negative `!=` reads plainly and takes it (RADD-1139).
    assert await _titles(db, actor, project, "epic.assignee IS EMPTY") == {"epic2", "issue2"}
    assert await _titles(db, actor, project, "epic.priority != blocker") == {
        "epic2",
        "issue2",
        "loner",
    }
    assert await _titles(db, actor, project, "epic.priority IN (blocker, normal)") == tree | {
        "epic2",
        "issue2",
    }


async def test_unfinished_epics_come_back_with_their_work(db, actor):
    """The motivating case: `epic.category != done` must not silently drop the
    epic itself — under the old strict reading its epic id was NULL, so even the
    negated form skipped it. Nor the work under NO epic (RADD-1139): "not under
    a finished epic" is plainly true of `loner`."""
    project, states = await _project_with_states(db)
    epic, *_ = await _ladder(db, actor, project, states)
    await items.update_item(db, epic.id, ItemUpdate(state_id=states["Done"].id), actor)

    assert await _titles(db, actor, project, "epic.category = done") == {
        "epic",
        "issue",
        "subtask",
    }
    assert await _titles(db, actor, project, "epic.category != done") == {
        "epic2",
        "issue2",
        "loner",
    }


@pytest.mark.parametrize(
    ("positive", "negative"),
    [
        ("epic.category = done", "epic.category != done"),
        ("epic.category IN (done)", "epic.category NOT IN (done)"),
        ("epic.state = 'In Progress'", "epic.state != 'In Progress'"),
        ("epic.state IN ('In Progress', Done)", "epic.state NOT IN ('In Progress', Done)"),
        ("parent.priority = blocker", "parent.priority != blocker"),
        ("parent.priority IN (blocker, high)", "parent.priority NOT IN (blocker, high)"),
        ("epic.assignee = me", "epic.assignee != me"),
    ],
)
async def test_positive_and_negative_forms_partition_the_project(db, actor, positive, negative):
    """RADD-1139: a negative predicate over a to-one relation is the complement
    of its positive form — an item with no epic/parent is on the negative side,
    never lost to both. Union = every item, intersection = nothing."""
    project, states = await _project_with_states(db)
    epic, *_ = await _ladder(db, actor, project, states)
    await items.update_item(db, epic.id, ItemUpdate(state_id=states["Done"].id), actor)
    everything = await _titles(db, actor, project, "")
    assert everything == {"epic", "issue", "subtask", "epic2", "issue2", "loner"}

    matched = await _titles(db, actor, project, positive)
    rest = await _titles(db, actor, project, negative)
    assert matched | rest == everything
    assert matched & rest == set()
    assert "loner" in rest  # the relation-less item reads as "not <that>"


async def test_bare_epic_key_none_and_empty(db, actor):
    project, states = await _project_with_states(db)
    epic, *_ = await _ladder(db, actor, project, states)
    epic_key = (await items.get_item(db, epic.id, actor)).key

    # `epic = KEY` is the whole tree, root included.
    assert await _titles(db, actor, project, f"epic = {epic_key}") == {"epic", "issue", "subtask"}
    # != is everything NOT in that tree — the other ladder, root included, and
    # the work no epic governs (RADD-1139).
    assert await _titles(db, actor, project, f"epic != {epic_key}") == {"epic2", "issue2", "loner"}
    # Only work no epic governs; an epic is never "epicless" now.
    assert await _titles(db, actor, project, "epic IS EMPTY") == {"loner"}
    assert await _titles(db, actor, project, "epic = none") == {"loner"}
    assert await _titles(db, actor, project, f"epic IN ({epic_key}, none)") == {
        "epic",
        "issue",
        "subtask",
        "loner",
    }
    assert await _titles(db, actor, project, "epic IS NOT EMPTY") == {
        "epic",
        "issue",
        "subtask",
        "epic2",
        "issue2",
    }
    # `kind = epic` is how you ask the question `epic IS EMPTY` used to answer.
    assert await _titles(db, actor, project, "epic IS EMPTY AND kind = epic") == set()
    assert await _titles(db, actor, project, "kind = epic") == {"epic", "epic2"}


async def test_parent_targets_the_direct_parent(db, actor):
    project, states = await _project_with_states(db)
    epic, issue, *_ = await _ladder(db, actor, project, states)
    epic_key = (await items.get_item(db, epic.id, actor)).key
    issue_key = (await items.get_item(db, issue.id, actor)).key

    # The subtask's DIRECT parent is the issue (default Triage state), not the epic.
    assert await _titles(db, actor, project, "parent.state = 'In Progress'") == {"issue"}
    # issue2's parent (epic2) also sits in the default Triage state.
    assert await _titles(db, actor, project, "parent.state = Triage") == {"subtask", "issue2"}
    assert await _titles(db, actor, project, "parent.priority = blocker") == {"issue"}
    assert await _titles(db, actor, project, "parent.assignee = me") == {"issue"}
    assert await _titles(db, actor, project, f"parent = {epic_key}") == {"issue"}
    assert await _titles(db, actor, project, f"parent = {issue_key}") == {"subtask"}
    assert await _titles(db, actor, project, f"parent IN ({epic_key}, {issue_key})") == {
        "issue",
        "subtask",
    }
    assert await _titles(db, actor, project, "parent IS EMPTY") == {"epic", "epic2", "loner"}


# --- cross-project ancestors (spec 80) + key aliases (spec 68) ---


async def test_cross_project_ancestor_matches_and_alias_resolves(db, actor):
    src, states = await _project_with_states(db, key_prefix="ASR")
    dst = await projects_service.create_project(
        db,
        ProjectCreate(key=f"ADS{uuid.uuid4().hex[:4].upper()}", name="Dst"),
    )
    epic = await items.create_item(
        db,
        ItemCreate(
            project_id=src.id,
            title="epic",
            kind=ItemKind.EPIC,
            state_id=states["In Progress"].id,
        ),
        actor,
    )
    await items.create_item(
        db, ItemCreate(project_id=src.id, title="issue", parent_id=epic.id), actor
    )
    result = await bulk.bulk_move_items(
        db, ItemBulkMove(item_ids=[epic.id], target_project_id=dst.id), actor
    )
    (moved,) = result.moved

    # Traversal is by id — the child still matches through its moved epic.
    assert await _titles(db, actor, src, "epic.state = 'In Progress'") == {"issue"}
    assert await _titles(db, actor, src, f"epic = {moved.new_key}") == {"issue"}
    # The pre-move key keeps working via the spec-68 alias table.
    assert await _titles(db, actor, src, f"epic = {moved.old_key}") == {"issue"}


# --- diagnostics: positioned 422s + ORDER BY rejection ---


async def test_bad_enum_values_are_positioned_errors(db, actor):
    project, _ = await _project_with_states(db)
    with pytest.raises(SlqError) as info:
        await _titles(db, actor, project, "epic.category = nope")
    assert info.value.position == len("epic.category = ")
    assert "invalid epic.category 'nope'" in str(info.value)

    with pytest.raises(SlqError) as info:
        await _titles(db, actor, project, "parent.priority = urgent")
    assert info.value.position == len("parent.priority = ")
    assert "invalid parent.priority 'urgent'" in str(info.value)


async def test_unknown_and_malformed_keys_are_positioned_errors(db, actor):
    project, _ = await _project_with_states(db)
    missing = f"Z{uuid.uuid4().hex[:6].upper()}-1"
    for field in ("epic", "parent"):
        q = f"{field} = {missing}"
        with pytest.raises(SlqError) as info:
            await _titles(db, actor, project, q)
        assert info.value.position == q.index(missing)
        assert f"unknown item '{missing}'" in str(info.value)

    with pytest.raises(SlqError) as info:
        await _titles(db, actor, project, "epic = 42")
    assert info.value.position == len("epic = ")
    assert "expected an item key like TD-12" in str(info.value)


@pytest.mark.parametrize(
    "field",
    ["epic", "epic.state", "epic.category", "epic.assignee", "epic.priority",
     "parent.state", "parent.category", "parent.assignee", "parent.priority"],
)
async def test_order_by_ancestor_fields_is_rejected(field):
    # Filter-only (spec 83): the same unsupported-sort error as other fields.
    with pytest.raises(SlqError) as info:
        await compile_query(
            None, parse(f"ORDER BY {field}"), definitions_by_key={}, current_user_id=uuid.uuid4()
        )
    assert info.value.position == len("ORDER BY ")
    assert f"field '{field}' is not sortable" in str(info.value)


# --- suggest: field completion + reused value sources ---


async def test_suggest_completes_ancestor_field_names():
    response = await suggestions_for(
        None, q="epic", cursor=4, scope=SuggestScope(),
        definitions_by_key={},
    )
    listed = set(s.value for s in response.suggestions)
    assert {"epic", "epic.state", "epic.category", "epic.assignee", "epic.priority"} <= listed

    response = await suggestions_for(
        None, q="parent.", cursor=7, scope=SuggestScope(),
        definitions_by_key={},
    )
    assert set(s.value for s in response.suggestions) == {
        "parent.state", "parent.category", "parent.assignee", "parent.priority",
    }


async def test_suggest_reuses_enum_value_sources():
    async def suggested(q):
        response = await suggestions_for(
            None, q=q, cursor=len(q), scope=SuggestScope(),
            definitions_by_key={},
        )
        return set(s.value for s in response.suggestions)

    from radd.modules.workflow.types import StateCategory

    assert await suggested("epic.priority = ") == {p.value for p in Priority}
    assert await suggested("parent.category = ") == {c.value for c in StateCategory}


async def test_suggest_bare_epic_offers_none_then_item_keys(db, actor):
    project, states = await _project_with_states(db)
    epic, *_ = await _ladder(db, actor, project, states)
    epic_key = (await items.get_item(db, epic.id, actor)).key
    response = await suggestions_for(
        db,
        q="epic = ",
        cursor=len("epic = "),
        scope=SuggestScope(project=project),
        definitions_by_key={},
    )
    listed = [s.value for s in response.suggestions]
    assert listed[0] == "none"
    assert epic_key in listed


# --- the hydrated `epic` ref (RADD-697) ---


async def test_hydrated_epic_ref_matches_the_slq_epic_field(db, actor):
    """The board's epic AXIS and SLQ's `epic` field must name the same epic for
    the same row — the axis groups client-side off `ItemRead.epic`, the query
    compiles `hierarchy.nearest_epic_case` in SQL, and two definitions of "the
    epic of an item" would silently disagree (a subtask is two hops from its
    epic, which no client can walk).
    """
    project, states = await _project_with_states(db)
    await _ladder(db, actor, project, states)

    reads = {
        r.title: r
        for r in await items.list_items(
            db, actor=actor, filters=ItemListFilters(project_id=project.id), limit=50, offset=0
        )
    }
    epic_key = reads["epic"].key

    # Self, parent, grandparent — and null for work no epic governs.
    assert reads["epic"].epic is not None and reads["epic"].epic.key == epic_key
    assert reads["issue"].epic is not None and reads["issue"].epic.key == epic_key
    assert reads["subtask"].epic is not None and reads["subtask"].epic.key == epic_key
    assert reads["loner"].epic is None
    assert reads["issue2"].epic is not None and reads["issue2"].epic.title == "epic2"

    # The agreement itself: everything the hydrator attributes to this epic is
    # exactly what `epic = <key>` returns.
    by_ref = {title for title, read in reads.items() if read.epic and read.epic.key == epic_key}
    assert by_ref == await _titles(db, actor, project, f"epic = {epic_key}")
    assert {t for t, r in reads.items() if r.epic is None} == await _titles(
        db, actor, project, "epic IS EMPTY"
    )
