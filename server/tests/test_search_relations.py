"""search_index carries relation columns (RADD-841), and search honours every
registered item relation — not only the mirrored ones (RADD-1030).

The prerequisite for relations reaching search (RADD-823/817): a
relation-scoped actor must be able to filter FTS results by reporter/
assignee/team without joining work_items per query. Three facts are pinned:
the indexer writes the columns from the event payload, an item.updated
re-index follows a change, and the bulk sweep repairs a repoint that never
emitted an item event (the user-merge shape).

The second half (RADD-1030) is the bug that mirror set caused: a relation
whose membership lives in ANOTHER table — `@participant` — had no mirror
column, so `_relation_index_clause` compiled `false()` for the project and a
shared item was invisible to /search while the list path returned it. The
tests below assert PARITY between the two paths, because that divergence is
the failure mode and neither path alone can show it.

Rolled-back transactions on the compose DB.
"""

import logging
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole

# Side effect: the workflow module's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.items import service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.participants import service as participants
from radd.modules.participants.schemas import ParticipantAdd
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.search import indexer
from radd.modules.search import service as search_service
from radd.modules.search.models import SearchIndexRow
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"sr-{uuid.uuid4().hex[:8]}@example.com", name="SR Admin", instance_role="admin"
    )
    db.add(user)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    return user


def _event(item, project, *, reporter=None, assignee=None, team=None):
    """The real payload shape (RADD-922): everything about the item nested under
    `item`, with NESTED refs for the relations."""
    return SimpleNamespace(
        entity_id=str(item.id),
        payload={
            "item": {
                "id": str(item.id),
                "project": {"id": str(project.id), "key": project.key, "name": project.name},
                "key": item.key,
                "title": item.title,
                "description": "",
                "reporter": {"id": str(reporter)} if reporter else None,
                "assignee": {"id": str(assignee)} if assignee else None,
                "team": {"id": str(team)} if team else None,
            }
        },
    )


async def test_index_writes_and_follows_the_relation_columns(db, admin):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SR{uuid.uuid4().hex[:4].upper()}", name="S")
    )
    team = await teams_service.create_team(db, TeamCreate(name=f"SR {uuid.uuid4().hex[:6]}"))
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="anchored"), admin
    )

    await indexer._index_item(
        db, _event(item, project, reporter=admin.id, assignee=admin.id, team=team.id)
    )
    row = await db.get(SearchIndexRow, item.id)
    assert row is not None
    assert row.reporter_id == admin.id
    assert row.assignee_id == admin.id
    assert row.team_id == team.id

    # An item.updated after unassign/re-route re-indexes the mirror.
    await indexer._index_item(db, _event(item, project, reporter=admin.id))
    await db.refresh(row)
    assert row.reporter_id == admin.id
    assert row.assignee_id is None
    assert row.team_id is None


async def test_partial_payload_never_nulls_a_good_mirror(db, admin):
    """A payload that does not SPEAK about a relation must not erase it — the
    RADD-840 oracle tests' minimal payloads are exactly this shape."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SP{uuid.uuid4().hex[:4].upper()}", name="S")
    )
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="kept"), admin
    )
    await indexer._index_item(db, _event(item, project, reporter=admin.id))
    bare = SimpleNamespace(
        entity_id=str(item.id),
        payload={
            "item": {
                "id": str(item.id),
                "project": {"id": str(project.id), "key": project.key, "name": project.name},
                "key": item.key,
                "title": item.title,
                "description": "",
            }
        },
    )
    await indexer._index_item(db, bare)
    row = await db.get(SearchIndexRow, item.id)
    assert row is not None and row.reporter_id == admin.id


async def test_sweep_repairs_a_repoint_that_emitted_no_item_event(db, admin):
    """The user-merge shape: work_items.assignee_id rewritten in bulk SQL with
    no item.updated — the sweep re-mirrors from the owning table."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SW{uuid.uuid4().hex[:4].upper()}", name="S")
    )
    successor = User(
        email=f"sr-{uuid.uuid4().hex[:8]}@example.com", name="Successor", instance_role="member"
    )
    db.add(successor)
    await db.flush()
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="merged", assignee_id=admin.id), admin
    )
    await indexer._index_item(db, _event(item, project, reporter=admin.id, assignee=admin.id))

    await db.execute(
        update(WorkItem).where(WorkItem.id == item.id).values(assignee_id=successor.id)
    )
    await indexer.sync_relation_columns(db)
    row = await db.get(SearchIndexRow, item.id)
    assert row is not None and row.assignee_id == successor.id
    assert row.reporter_id == admin.id


# --- RADD-1030: the relations the mirror does NOT carry ------------------------
#
# Twelve characters on purpose: `KEY_QUERY_RE` claims any bare word of ten or
# fewer, and a key-shaped query takes the quick-open branch instead of FTS —
# which would make these tests pass without exercising the tsquery path at all.
_TOKEN = "quokkasearch"


async def _outsider(db, name: str) -> User:
    """An active staff account holding ONLY the Baseline: no roles, no
    memberships, no standing anywhere. It reads items solely through a
    relation (`item.read@own`, `item.read@participant`)."""
    user = User(
        email=f"sr-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _indexed_project(db, admin):
    """A project holding two INDEXED items: one to share, one never shared."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SP{uuid.uuid4().hex[:4].upper()}", name="Shared")
    )
    shared = await items.create_item(
        db, ItemCreate(project_id=project.id, title=f"{_TOKEN} shared ticket"), admin
    )
    private = await items.create_item(
        db, ItemCreate(project_id=project.id, title=f"{_TOKEN} private ticket"), admin
    )
    for item in (shared, private):
        await indexer._index_item(db, _event(item, project, reporter=admin.id))
    return project, shared, private


async def _found(db, user) -> set:
    return {hit.item_id for hit in await search_service.search(db, user, _TOKEN, limit=50)}


async def _listed(db, user, project) -> set:
    rows = await items.list_items(
        db, actor=user, filters=ItemListFilters(project_id=project.id), limit=50, offset=0
    )
    return {row.id for row in rows}


async def test_a_shared_item_is_findable_and_search_agrees_with_the_list(db, admin):
    """The live-proven bug: `@participant` had no mirror column, so the search
    arm for the project compiled `false()` — the list path returned the shared
    item and /search returned nothing. Parity is the assertion, both ways."""
    project, shared, private = await _indexed_project(db, admin)
    outsider = await _outsider(db, "Second Reporter")

    assert await _found(db, outsider) == set()  # nothing shared yet
    assert await _listed(db, outsider, project) == set()

    await participants.add_participant(
        db, shared.id, ParticipantAdd(user_id=outsider.id), admin
    )
    assert await _found(db, outsider) == {shared.id}
    assert await _found(db, outsider) == await _listed(db, outsider, project)
    assert private.id not in await _found(db, outsider)  # the gate still bites


async def test_a_team_share_is_findable_by_current_members(db, admin):
    """A team participant row covers its CURRENT members — the same live
    semantics the notify fan-out has, inherited because search compiles the
    registered spec rather than restating it."""
    project, shared, _private = await _indexed_project(db, admin)
    team = await teams_service.create_team(db, TeamCreate(name=f"SR {uuid.uuid4().hex[:6]}"))
    member = await _outsider(db, "Team Member")
    await teams_service.add_team_member(db, team.id, member.id)

    await participants.add_participant(db, shared.id, ParticipantAdd(team_id=team.id), admin)
    assert await _found(db, member) == {shared.id}
    assert await _found(db, member) == await _listed(db, member, project)


async def test_the_mirrored_relations_are_unchanged(db, admin):
    """The regression guard for the other direction: compiling extra relations
    must not widen the mirror ones. A Baseline-only reporter finds their OWN
    item and no more, and a stranger finds nothing at all."""
    project, _shared, _private = await _indexed_project(db, admin)
    reporter = await _outsider(db, "First Reporter")
    stranger = await _outsider(db, "Stranger")
    mine = await items.create_item(
        db,
        ItemCreate(
            project_id=project.id, title=f"{_TOKEN} my own ask", reporter_id=reporter.id
        ),
        admin,
    )
    await indexer._index_item(db, _event(mine, project, reporter=reporter.id))

    assert await _found(db, reporter) == {mine.id}
    assert await _found(db, reporter) == await _listed(db, reporter, project)
    assert await _found(db, stranger) == set()


async def test_relations_compose_across_projects_in_one_query(db, admin):
    """Relations are per-PROJECT facts, so the clause is an OR of per-project
    arms and the compiled participant subquery is reused across them. One
    query, two different reasons to be admitted, and each project's answer is
    still its own."""
    first, shared, private = await _indexed_project(db, admin)
    second, elsewhere, _also_private = await _indexed_project(db, admin)
    outsider = await _outsider(db, "Both Ways")

    # Reported by them in the FIRST project; shared with them in the SECOND.
    mine = await items.create_item(
        db,
        ItemCreate(project_id=first.id, title=f"{_TOKEN} filed by me", reporter_id=outsider.id),
        admin,
    )
    await indexer._index_item(db, _event(mine, first, reporter=outsider.id))
    await participants.add_participant(
        db, elsewhere.id, ParticipantAdd(user_id=outsider.id), admin
    )

    assert await _found(db, outsider) == {mine.id, elsewhere.id}
    assert await _listed(db, outsider, first) == {mine.id}
    assert await _listed(db, outsider, second) == {elsewhere.id}
    assert private.id not in await _found(db, outsider)
    assert shared.id not in await _found(db, outsider)


# --- the compile step itself (pure: registry + expression, no database) --------


def _relation_actor(team_ids=()):
    from radd.kernel.specs import RelationActor

    return RelationActor(user_id=uuid.uuid4(), team_ids=frozenset(team_ids))


def test_the_mirror_constant_matches_the_clauses_it_documents():
    """`_INDEX_RELATION_COLUMNS` is the skip list for the registry pass, so a
    drift between it and the mirror clauses would silently recompile a mirrored
    relation (slow) or skip a registered one (a narrowing bug)."""
    clauses = search_service._relation_clauses(_relation_actor(), set())
    assert tuple(clauses) == search_service._INDEX_RELATION_COLUMNS


def test_participant_compiles_onto_the_index_without_touching_work_items():
    """The d841 mirror rule must survive the fix: the participant subquery is
    over `item_participants`, and only its ANCHOR moves to search_index."""
    clauses = search_service._relation_clauses(_relation_actor(), {"participant"})
    assert "participant" in clauses
    sql = str(clauses["participant"])
    assert "search_index.item_id IN" in sql
    assert "item_participants" in sql
    assert "work_items" not in sql


def test_a_subquery_correlating_back_to_work_items_is_refused_too():
    """The refusal has to look INSIDE the subquery, not just at the anchor: a
    correlated where-form would otherwise sneak the join back in, and the
    mirror exists precisely so /search never touches work_items."""
    from sqlalchemy import select

    from radd.modules.participants.models import ItemParticipant

    nested = WorkItem.id.in_(
        select(ItemParticipant.item_id).where(WorkItem.title == "anything")
    )
    assert search_service._rebind_to_index(nested) is None


def test_a_relation_the_mirror_cannot_carry_is_refused_and_reported(caplog):
    """Fail CLOSED, and say so. A relation whose where-form reaches a
    work_items COLUMN cannot be answered from the mirror; dropping it narrows
    results, which is safe — going quiet about it is what is not."""
    from radd.kernel.registry import register_relation, registries
    from radd.kernel.specs import RelationSpec

    register_relation(
        RelationSpec(
            resource="item",
            key="reviewed",
            label="they reviewed",
            # A work_items column, not the id anchor — unmirrorable by design.
            where=lambda actor: WorkItem.assignee_id == actor.user_id,
            holds=lambda actor, item: item.assignee_id == actor.user_id,
        )
    )
    search_service._unmirrorable_warned.discard("reviewed")
    try:
        with caplog.at_level(logging.WARNING, logger=search_service.__name__):
            clauses = search_service._relation_clauses(_relation_actor(), {"reviewed"})
        assert "reviewed" not in clauses
        assert "reviewed" in caplog.text and "work_items" in caplog.text
    finally:
        registries.relations.pop(("item", "reviewed"), None)
        search_service._unmirrorable_warned.discard("reviewed")
