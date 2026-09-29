"""Cross-project hierarchy & links (spec 80): the same-PROJECT invariant on
parents and manual links is lifted — items link/parent freely across projects
(spec 86 removed the workspace boundary; there is only one global scope). The
kind ladder (epic ← issue ← subtask) is unchanged.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid

import pytest

from radd.exceptions import ConflictError
from radd.modules.items import service as items
from radd.modules.items.enums import ItemKind
from radd.modules.items.models import ItemKeyAlias
from radd.modules.linktypes.types import ItemLinkType
from radd.modules.items.schemas import ItemCreate, ItemLinkCreate, ItemUpdate

from _factories import make_project


async def test_cross_project_parent_accepted(db, actor):
    p1 = await make_project(db, "PA")
    p2 = await make_project(db, "PB")
    epic = await items.create_item(
        db, ItemCreate(project_id=p1.id, title="epic", kind=ItemKind.EPIC), actor
    )
    # Create path: an issue in P2 under an epic in P1.
    issue = await items.create_item(
        db, ItemCreate(project_id=p2.id, title="issue", parent_id=epic.id), actor
    )
    assert issue.parent is not None and issue.parent.id == epic.id

    # Update path: re-parenting an existing item across projects works too.
    orphan = await items.create_item(db, ItemCreate(project_id=p2.id, title="orphan"), actor)
    updated = await items.update_item(db, orphan.id, ItemUpdate(parent_id=epic.id), actor)
    assert updated.parent is not None and updated.parent.id == epic.id


async def test_kind_ladder_still_enforced_across_projects(db, actor):
    p1 = await make_project(db, "LA")
    p2 = await make_project(db, "LB")
    issue = await items.create_item(db, ItemCreate(project_id=p1.id, title="issue"), actor)
    # An issue's parent must be an EPIC — crossing projects doesn't relax the ladder.
    with pytest.raises(ConflictError, match="must be of kind"):
        await items.create_item(
            db, ItemCreate(project_id=p2.id, title="child", parent_id=issue.id), actor
        )


async def test_cross_project_link_accepted(db, actor):
    p1 = await make_project(db, "KA")
    p2 = await make_project(db, "KB")
    source = await items.create_item(db, ItemCreate(project_id=p1.id, title="source"), actor)
    target = await items.create_item(db, ItemCreate(project_id=p2.id, title="target"), actor)
    read = await items.add_item_link(
        db,
        source.id,
        ItemLinkCreate(target_id=target.id, link_type=ItemLinkType.BLOCKS),
        actor,
    )
    assert any(link.item.id == target.id for link in read.links.outgoing)


async def test_link_search_ranks_same_project_first(db, actor):
    p1 = await make_project(db, "SA")
    p2 = await make_project(db, "SB")
    marker = f"needle-{uuid.uuid4().hex[:6]}"
    # Created in the OTHER project first — ordering must come from the tier,
    # not from creation order or numbers.
    other = await items.create_item(
        db, ItemCreate(project_id=p2.id, title=f"{marker} other"), actor
    )
    mine = await items.create_item(db, ItemCreate(project_id=p1.id, title=f"{marker} mine"), actor)
    results = await items.link_search(db, project_id=p1.id, q=marker, actor=actor, limit=8)
    ids = [result.id for result in results]
    assert set(ids) == {mine.id, other.id}
    assert ids.index(mine.id) < ids.index(other.id)  # same-project tier first
    by_id = {result.id: result for result in results}
    assert by_id[other.id].key.startswith("SB")  # keys carry the item's OWN project
    assert by_id[mine.id].key.startswith("SA")


async def test_typed_key_links_the_project_it_names(db, actor):
    """RADD-1490: `DEV-23` typed on a TD item means DEV-23, never TD-23."""
    p1 = await make_project(db, "TA")
    p2 = await make_project(db, "TB")
    source = await items.create_item(db, ItemCreate(project_id=p1.id, title="source"), actor)
    own = await items.create_item(db, ItemCreate(project_id=p1.id, title="own"), actor)
    await items.create_item(db, ItemCreate(project_id=p2.id, title="filler"), actor)
    other = await items.create_item(db, ItemCreate(project_id=p2.id, title="other"), actor)
    # Same number in both projects, so a bare-number resolver would pick `own`.
    assert own.number == other.number
    read = await items.add_item_link(
        db,
        source.id,
        ItemLinkCreate(target_key=other.key.lower(), link_type=ItemLinkType.BLOCKS),
        actor,
    )
    assert [link.item.id for link in read.links.outgoing] == [other.id]
    # The bare-number form still means the source item's own project.
    read = await items.add_item_link(
        db,
        source.id,
        ItemLinkCreate(target_number=own.number, link_type=ItemLinkType.RELATES),
        actor,
    )
    assert own.id in {link.item.id for link in read.links.outgoing}
    # A spec-68 alias resolves too — an old key keeps naming its item after a move.
    db.add(ItemKeyAlias(old_key="OLDKEY-7", item_id=other.id))
    await db.flush()
    read = await items.add_item_link(
        db, own.id, ItemLinkCreate(target_key="oldkey-7", link_type=ItemLinkType.RELATES), actor
    )
    assert [link.item.id for link in read.links.outgoing] == [other.id]
    # Two addresses at once is a refusal, not a silent preference.
    with pytest.raises(ConflictError, match="one way"):
        await items.add_item_link(
            db,
            own.id,
            ItemLinkCreate(target_key=other.key, target_number=1, link_type=ItemLinkType.BLOCKS),
            actor,
        )


async def test_link_search_leads_with_the_named_key(db, actor):
    """RADD-1490: the typeahead for a full key leads with that row, ahead of the
    anchor project's own item of the same number."""
    p1 = await make_project(db, "NA")
    p2 = await make_project(db, "NB")
    own = await items.create_item(db, ItemCreate(project_id=p1.id, title="own"), actor)
    other = await items.create_item(db, ItemCreate(project_id=p2.id, title="other"), actor)
    assert own.number == other.number
    results = await items.link_search(
        db, project_id=p1.id, q=other.key.lower(), actor=actor, limit=8
    )
    assert results[0].id == other.id
    assert {r.id for r in results} >= {own.id, other.id}  # the number match still lists `own`
    # A bare number keeps the anchor project first (spec 80's tier).
    results = await items.link_search(db, project_id=p1.id, q=str(own.number), actor=actor, limit=8)
    assert results[0].id == own.id
