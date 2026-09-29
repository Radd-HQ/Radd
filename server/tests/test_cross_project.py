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
from radd.modules.items.grouped import grouped_items
from radd.modules.items.grouped_axes import HIDDEN_EPIC_BUCKET
from radd.modules.items.grouped_schemas import GroupPageRequest
from radd.modules.items.models import ItemKeyAlias
from radd.modules.auth import roles
from radd.modules.auth.models import GlobalRoleGrant, Role
from radd.modules.auth.types import BuiltinRoleKey
from radd.exceptions import NotFoundError
from sqlalchemy import select

from _factories import make_user
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


async def _member_of(db, project):
    """A person who reads ONE project through the builtin Member role and holds
    nothing else — the shape a TD-only teammate has (never an admin, whose
    every check passes vacuously)."""
    await roles.ensure_builtin_roles(db)
    member = await db.scalar(select(Role).where(Role.key == BuiltinRoleKey.MEMBER.value))
    person = await make_user(db, name="TD only")
    db.add(GlobalRoleGrant(role_id=member.id, user_id=person.id, project_id=project.id))
    await db.flush()
    return person


async def test_hidden_parent_is_flagged_and_not_replaceable(db, actor):
    """RADD-1491: a parent the actor cannot read is reported as hidden (never as
    absent), files the row under the hidden-epic bucket, and cannot be replaced
    by that actor — while a project manager still can."""
    dev = await make_project(db, "HD")
    td = await make_project(db, "HT")
    epic = await items.create_item(
        db, ItemCreate(project_id=dev.id, title="dev epic", kind=ItemKind.EPIC), actor
    )
    issue = await items.create_item(
        db, ItemCreate(project_id=td.id, title="td issue", parent_id=epic.id), actor
    )
    subtask = await items.create_item(
        db,
        ItemCreate(project_id=td.id, title="td step", kind=ItemKind.SUBTASK, parent_id=issue.id),
        actor,
    )
    own_epic = await items.create_item(
        db, ItemCreate(project_id=td.id, title="td epic", kind=ItemKind.EPIC), actor
    )
    person = await _member_of(db, td)
    # The actor really cannot read the DEV epic — otherwise every assertion below is vacuous.
    with pytest.raises(NotFoundError):
        await items.get_item(db, epic.id, person)

    read = await items.get_item(db, issue.id, person)
    assert read.parent is None and read.parent_hidden is True
    assert read.epic is None and read.epic_hidden is True
    step = await items.get_item(db, subtask.id, person)
    assert step.parent is not None and step.parent_hidden is False  # its parent is readable
    assert step.epic is None and step.epic_hidden is True  # the walk hit the withheld rung
    # The admin sees the same rows with nothing hidden.
    full = await items.get_item(db, issue.id, actor)
    assert full.parent is not None and full.parent_hidden is False and full.epic_hidden is False

    # Board grouped by epic: the hidden bucket, not "no epic".
    page = await grouped_items(
        db, person, GroupPageRequest(project_id=td.id, axis="epic", summary_only=True)
    )
    assert page.column_totals.get(HIDDEN_EPIC_BUCKET) == 2
    assert page.column_labels[HIDDEN_EPIC_BUCKET] == "Epic you cannot see"

    # Replacing what you cannot see is refused; clearing it too.
    with pytest.raises(ConflictError, match="cannot read"):
        await items.update_item(db, issue.id, ItemUpdate(parent_id=own_epic.id), person)
    with pytest.raises(ConflictError, match="cannot read"):
        await items.update_item(db, issue.id, ItemUpdate(parent_id=None), person)
    # Restating the same parent is not a replacement.
    same = await items.update_item(
        db, issue.id, ItemUpdate(parent_id=epic.id, title="renamed"), person
    )
    assert same.parent_hidden is True and same.title == "renamed"
    # A manager of the child's project may re-home it.
    moved = await items.update_item(db, issue.id, ItemUpdate(parent_id=own_epic.id), actor)
    assert moved.parent is not None and moved.parent.id == own_epic.id


async def test_subtask_lives_in_its_parents_project(db, actor):
    """RADD-1492: epic ← issue crosses projects; issue ← subtask does not, on
    create, on re-parent and on convert — and the parent search for issues stays
    in the anchor project."""
    dev = await make_project(db, "SD")
    td = await make_project(db, "ST")
    dev_issue = await items.create_item(db, ItemCreate(project_id=dev.id, title="dev issue"), actor)
    td_issue = await items.create_item(db, ItemCreate(project_id=td.id, title="td issue"), actor)
    with pytest.raises(ConflictError, match="lives in its parent's project"):
        await items.create_item(
            db,
            ItemCreate(
                project_id=td.id, title="step", kind=ItemKind.SUBTASK, parent_id=dev_issue.id
            ),
            actor,
        )
    step = await items.create_item(
        db,
        ItemCreate(project_id=td.id, title="step", kind=ItemKind.SUBTASK, parent_id=td_issue.id),
        actor,
    )
    with pytest.raises(ConflictError, match="lives in its parent's project"):
        await items.update_item(db, step.id, ItemUpdate(parent_id=dev_issue.id), actor)
    # Convert: a TD issue may not become a subtask of a DEV issue either.
    loose = await items.create_item(db, ItemCreate(project_id=td.id, title="loose"), actor)
    with pytest.raises(ConflictError, match="lives in its parent's project"):
        await items.convert_item_kind(
            db, loose.id, actor, kind=ItemKind.SUBTASK, parent_id=dev_issue.id
        )
    # The picker's search for a subtask's parent: issues in THIS project only.
    hits = await items.link_search(
        db,
        project_id=td.id,
        q="issue",
        actor=actor,
        limit=8,
        kind=ItemKind.ISSUE,
        same_project=True,
    )
    assert {hit.id for hit in hits} == {td_issue.id}
