"""Batch hydration of WorkItem rows into ItemRead — one grouped/IN query per relation, no N+1."""

import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import service as auth
from radd.modules.cycles import service as cycles_service
from radd.modules.labels import service as labels_service
from radd.modules.releases import service as releases_service
from radd.modules.releases.types import ReleaseStatus
from radd.modules.teams import service as teams
from radd.modules.itemtypes import service as itemtypes
from radd.modules.workflow import service as workflow
from radd.modules.workflow.schemas import StateRef
from radd.modules.projects import service as projects_service

from radd.modules.linktypes import service as linktypes_service

from .enums import ItemKind, ItemVisibility
from .models import ItemLabel, ItemLink, ItemStar, WorkItem
from .schemas import (
    CycleRef,
    ItemLinkRead,
    ItemLinks,
    ItemRead,
    LinkItem,
    ParentRef,
    ReleaseRef,
    TeamRef,
    TypeRef,
    UserRef,
)

# Items can't declare a dependency on comments (comments depends on items), so the
# comment-count hydration soft-imports it and degrades to 0 when the module is disabled.
COMMENTS_MODULE_PATH = "radd.modules.comments"

# Rungs walked looking for an item's epic: itself, its parent, its grandparent.
# That is the whole hierarchy (epic <- issue <- subtask), so the walk terminates
# by shape rather than by trusting the data to be acyclic.
_EPIC_LOOKUP_RUNGS = len(ItemKind)


def _user_ref(user) -> UserRef:
    return UserRef(
        id=user.id,
        name=user.name,
        avatar_color=user.avatar_color,
        avatar_emoji=user.avatar_emoji,
        avatar_url=user.avatar_url,
    )


async def label_names(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    rows = (
        await session.execute(
            select(ItemLabel.item_id, ItemLabel.label_id).where(
                ItemLabel.item_id.in_(set(item_ids))
            )
        )
    ).all()
    labels = await labels_service.labels_by_ids(session, {label_id for _, label_id in rows})
    names: dict[uuid.UUID, list[str]] = {}
    for item_id, label_id in rows:
        names.setdefault(item_id, []).append(labels[label_id].name)
    return {item_id: sorted(item_labels) for item_id, item_labels in names.items()}


async def _child_counts(
    session: AsyncSession,
    item_ids: Iterable[uuid.UUID],
    readable_project_ids: frozenset[uuid.UUID] | None,
    relation_clause=None,
) -> dict[uuid.UUID, int]:
    query = (
        select(WorkItem.parent_id, func.count())
        .where(WorkItem.parent_id.in_(set(item_ids)))
        .group_by(WorkItem.parent_id)
    )
    if readable_project_ids is not None:
        query = query.where(WorkItem.project_id.in_(readable_project_ids))
    if relation_clause is not None:
        query = query.where(relation_clause)  # RADD-835: counts must match rows
    rows = await session.execute(query)
    return dict(rows.all())


async def _comment_counts(
    session: AsyncSession, items: list[WorkItem], internal_visible: set[uuid.UUID] | None
) -> dict[uuid.UUID, int]:
    """Per-item comment counts, respecting comment visibility (spec 07).

    `internal_visible` = project ids where the actor holds COMMENT_READ_INTERNAL;
    None = trusted context, count everything.
    """
    if COMMENTS_MODULE_PATH not in settings.modules:
        return {}
    from radd.modules.comments import service as comments  # soft dep — see note at top

    if internal_visible is None:
        return await comments.comment_counts(session, [i.id for i in items])
    full = [i.id for i in items if i.project_id in internal_visible]
    public_only = [i.id for i in items if i.project_id not in internal_visible]
    counts = await comments.comment_counts(session, full)
    counts |= await comments.comment_counts(session, public_only, include_internal=False)
    return counts


async def _parents_by_id(
    session: AsyncSession, parent_ids: set[uuid.UUID], relation_clause=None
) -> dict[uuid.UUID, WorkItem]:
    if not parent_ids:
        return {}
    query = select(WorkItem).where(WorkItem.id.in_(parent_ids))
    # RADD-835: a hidden ROW in a readable project is hidden too — the project
    # filter alone predates relations, and a subtask's payload carried its
    # restricted parent's title through exactly this query.
    if relation_clause is not None:
        query = query.where(relation_clause)
    result = await session.execute(query)
    return {parent.id: parent for parent in result.scalars()}


async def _links(
    session: AsyncSession,
    items: list[WorkItem],
    readable_project_ids: frozenset[uuid.UUID] | None,
    relation_clause=None,
) -> dict[uuid.UUID, ItemLinks]:
    """Every dependency edge touching these items, split by direction — no N+1.

    One query for the link rows, one to resolve the far-end items' keys/titles.
    An edge whose far end sits in a project the actor can't read is dropped
    (RADD-839) — the key+title of a hidden item is exactly what the restriction
    protects.
    """
    result: dict[uuid.UUID, ItemLinks] = {i.id: ItemLinks() for i in items}
    item_ids = set(result)
    if not item_ids:
        return result
    rows = list(
        (
            await session.execute(
                select(ItemLink).where(
                    or_(
                        ItemLink.source_item_id.in_(item_ids),
                        ItemLink.target_item_id.in_(item_ids),
                    )
                )
            )
        ).scalars()
    )
    referenced = {r.source_item_id for r in rows} | {r.target_item_id for r in rows}
    far_query = select(WorkItem).where(WorkItem.id.in_(referenced))
    if relation_clause is not None:
        # RADD-835: the RELATION row filter, on top of the project one below —
        # a link's far end must pass the same seam every list read passes.
        far_query = far_query.where(relation_clause)
    others = (await session.execute(far_query)).scalars()
    by_id = {
        o.id: o
        for o in others
        if readable_project_ids is None or o.project_id in readable_project_ids
    }
    keys = await projects_service.project_keys(session, {o.project_id for o in by_id.values()})

    def ref(other_id: uuid.UUID) -> LinkItem:
        other = by_id[other_id]
        return LinkItem(id=other.id, key=f"{keys[other.project_id]}-{other.number}", title=other.title)

    # Link-type catalog (spec 91) — resolves each edge's directional label. A few rows.
    catalog = await linktypes_service.catalog(session)
    for row in rows:
        definition = catalog.get(row.link_type)
        if row.source_item_id in result and row.target_item_id in by_id:
            result[row.source_item_id].outgoing.append(
                ItemLinkRead(
                    id=row.id,
                    link_type=row.link_type,
                    label=linktypes_service.label_for(definition, incoming=False),
                    item=ref(row.target_item_id),
                )
            )
        if row.target_item_id in result and row.source_item_id in by_id:
            result[row.target_item_id].incoming.append(
                ItemLinkRead(
                    id=row.id,
                    link_type=row.link_type,
                    label=linktypes_service.label_for(definition, incoming=True),
                    item=ref(row.source_item_id),
                )
            )
    for links in result.values():
        links.outgoing.sort(key=lambda link: (link.link_type, link.item.key))
        links.incoming.sort(key=lambda link: (link.link_type, link.item.key))
    return result


async def _starred_ids(
    session: AsyncSession, actor_id: uuid.UUID | None, item_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of these items the requesting user has starred (spec 24). Personal —
    empty when there is no actor (system/anonymous hydration)."""
    ids = set(item_ids)
    if actor_id is None or not ids:
        return set()
    rows = await session.execute(
        select(ItemStar.item_id).where(ItemStar.user_id == actor_id, ItemStar.item_id.in_(ids))
    )
    return set(rows.scalars())


async def hydrate(
    session: AsyncSession,
    items: list[WorkItem],
    *,
    internal_visible: set[uuid.UUID] | None = None,
    today: date | None = None,
    actor_id: uuid.UUID | None = None,
    readable_project_ids: frozenset[uuid.UUID] | None = None,
    relation_clause=None,
) -> list[ItemRead]:
    """`readable_project_ids` (RADD-839): the projects the ACTOR may read — parent
    breadcrumbs, epic refs, link targets and child counts outside it are dropped
    from the payload (the row survives; the cross-project reference does not).
    None = trusted context (system consumers), nothing dropped.

    `relation_clause` (RADD-835): the RADD-823 row filter for the same actor —
    `items.service.visibility.relation_read_clause` — applied to every
    cross-item reference this assembles (parents, link far-ends, child
    counts). The project filter answers "which projects may they read"; this
    one answers "which ROWS", and since the floor narrowed to item.read@own
    the second question is the one that bites."""
    pivot = today or date.today()  # derives cycle status; injectable for determinism
    item_ids = [i.id for i in items]
    starred = await _starred_ids(session, actor_id, item_ids)
    parents = await _parents_by_id(
        session, {i.parent_id for i in items if i.parent_id}, relation_clause
    )
    # RADD-697: the epic axis needs the epic an item BELONGS TO, which is at most
    # two hops up (hierarchy: epic <- issue <- subtask). One extra batched
    # lookup for the grandparents, merged into the same map — a subtask's epic
    # is its parent-issue's parent, and no client can derive that from `parent`.
    parents |= await _parents_by_id(
        session,
        {p.parent_id for p in parents.values() if p.parent_id} - set(parents),
        relation_clause,
    )
    if readable_project_ids is not None:
        parents = {
            pid: parent
            for pid, parent in parents.items()
            if parent.project_id in readable_project_ids
        }
    project_ids = {i.project_id for i in items} | {p.project_id for p in parents.values()}
    keys = await projects_service.project_keys(session, project_ids)
    states = await workflow.states_by_ids(session, {i.state_id for i in items})
    labels = await label_names(session, item_ids)
    user_ids = {i.assignee_id for i in items if i.assignee_id}
    user_ids |= {i.reporter_id for i in items if i.reporter_id}
    users = await auth.users_by_ids(session, user_ids)
    team_map = await teams.teams_by_ids(session, {i.team_id for i in items if i.team_id})
    type_map = await itemtypes.types_by_ids(session, {i.type_id for i in items if i.type_id})
    cycles = await cycles_service.cycles_by_ids(session, {i.cycle_id for i in items if i.cycle_id})
    past_cycle_map = await cycles_service.past_cycles_by_item_ids(session, item_ids)
    releases = await releases_service.releases_by_ids(
        session, {i.release_id for i in items if i.release_id}
    )
    child_counts = await _child_counts(session, item_ids, readable_project_ids, relation_clause)
    comment_counts = await _comment_counts(session, items, internal_visible)
    links = await _links(session, items, readable_project_ids, relation_clause)

    def type_ref(type_id: uuid.UUID | None) -> TypeRef | None:
        if type_id is None or type_id not in type_map:
            return None
        t = type_map[type_id]
        return TypeRef(id=t.id, name=t.name, color=t.color, icon=t.icon)

    def parent_ref(parent_id: uuid.UUID | None) -> ParentRef | None:
        if parent_id is None:
            return None
        parent = parents.get(parent_id)  # absent = unreadable to the actor (RADD-839)
        if parent is None:
            return None
        return ParentRef(
            id=parent.id, key=f"{keys[parent.project_id]}-{parent.number}", title=parent.title
        )

    def epic_ref(item: WorkItem) -> ParentRef | None:
        """The epic this item belongs to — ITSELF, else its parent, else its
        grandparent (RADD-697). The Python mirror of `hierarchy.nearest_epic_case`,
        which is what SLQ's `epic` field compiles to: the axis and the query
        language must agree on what "the epic of an item" means, or a board
        grouped by epic would disagree with `epic = X` over the same rows.
        """
        node: WorkItem | None = item
        for _ in range(_EPIC_LOOKUP_RUNGS):
            if node is None:
                return None
            if node.kind == ItemKind.EPIC.value:
                return ParentRef(
                    id=node.id,
                    key=f"{keys[node.project_id]}-{node.number}",
                    title=node.title,
                )
            node = parents.get(node.parent_id) if node.parent_id else None
        return None

    def cycle_ref(cycle_id: uuid.UUID | None) -> CycleRef | None:
        if cycle_id is None:
            return None
        cycle = cycles[cycle_id]
        status = cycles_service.cycle_status(
            cycle.start_date, cycle.end_date, pivot, cycle.completed_at
        )
        return CycleRef(id=cycle.id, name=cycle.name, status=status)

    def past_cycle_refs(item_id: uuid.UUID) -> list[CycleRef]:
        return [
            CycleRef(
                id=c.id,
                name=c.name,
                status=cycles_service.cycle_status(c.start_date, c.end_date, pivot, c.completed_at),
            )
            for c in past_cycle_map.get(item_id, [])
        ]

    def release_ref(release_id: uuid.UUID | None) -> ReleaseRef | None:
        if release_id is None:
            return None
        release = releases[release_id]
        return ReleaseRef(id=release.id, version=release.version, status=ReleaseStatus(release.status))

    return [
        ItemRead(
            id=i.id,
            project_id=i.project_id,
            key=f"{keys[i.project_id]}-{i.number}",
            number=i.number,
            kind=ItemKind(i.kind),
            type=type_ref(i.type_id),
            title=i.title,
            description=i.description,
            state=StateRef.model_validate(states[i.state_id]),
            priority=i.priority,
            visibility=ItemVisibility(i.visibility),
            parent=parent_ref(i.parent_id),
            epic=epic_ref(i),
            assignee=(
                _user_ref(users[i.assignee_id])
                if i.assignee_id
                else None
            ),
            reporter=(
                _user_ref(users[i.reporter_id])
                if i.reporter_id and i.reporter_id in users
                else None
            ),
            team=(
                TeamRef(id=team_map[i.team_id].id, name=team_map[i.team_id].name)
                if i.team_id
                else None
            ),
            start_date=i.start_date,
            target_date=i.target_date,
            cycle=cycle_ref(i.cycle_id),
            past_cycles=past_cycle_refs(i.id),
            release=release_ref(i.release_id),
            flagged=i.flagged,
            estimate_points=i.estimate_points,
            archived_at=i.archived_at,
            starred=i.id in starred,
            links=links.get(i.id, ItemLinks()),
            child_count=child_counts.get(i.id, 0),
            comment_count=comment_counts.get(i.id, 0),
            labels=labels.get(i.id, []),
            custom_fields=i.custom_fields,
            created_at=i.created_at,
            updated_at=i.updated_at,
        )
        for i in items
    ]
