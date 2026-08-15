"""Item links: dependency typeahead, manual links, derived mention backlinks."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields
from radd.modules.linktypes import service as linktypes_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from ..enums import ItemEntity, ItemEvent, ItemKind, ItemLinkType
from .visibility import relation_read_clause
from ..mentions import parse_issue_keys
from ..models import ItemLink, WorkItem
from ..schemas import ItemLinkCreate, ItemLinkSearchResult, ItemRead
from .queries import find_item_by_key, require_item
from .read import _finish, _hydrate_one
from .visibility import _field_ctx


# --- link typeahead (dependency add-row autocomplete) ---


def _search_number(term: str) -> int | None:
    """Pull an item number from a search term: '23' or 'TD-23' -> 23, else None."""
    candidate = term.rsplit("-", 1)[1] if "-" in term else term
    return int(candidate) if candidate.isdigit() else None


async def link_search(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    q: str,
    actor: User,
    limit: int = 8,
    exclude_id: uuid.UUID | None = None,
) -> list[ItemLinkSearchResult]:
    """Typeahead candidates for a dependency link or parent pick: items across
    every project the actor can read (spec 80/86 — no boundary above that)
    matching `q` by title substring or number/key. Same-project matches
    rank first, newest-numbered within each tier. `exclude_id` drops the item
    being linked from (no self-link)."""
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, actor, Permission.ITEM_READ, project=project)
    # The memoised member floor (holds_base-aware, so a relation-qualified
    # reader still completes) + the RADD-817 row filter.
    readable_map = await authz.readable_projects(session, actor)
    query = select(WorkItem).where(WorkItem.project_id.in_(readable_map.keys()))
    relation_clause = await relation_read_clause(session, actor, readable_map)
    if relation_clause is not None:
        query = query.where(relation_clause)
    if exclude_id is not None:
        query = query.where(WorkItem.id != exclude_id)
    term = q.strip()
    if term:
        conditions = [WorkItem.title.ilike(f"%{term}%")]
        number = _search_number(term)
        if number is not None:
            conditions.append(WorkItem.number == number)
        query = query.where(or_(*conditions))
    # Two-tier ordering (spec 80): the anchor project's own items first.
    query = query.order_by(
        (WorkItem.project_id == project_id).desc(), WorkItem.number.desc()
    ).limit(limit)
    items = list((await session.execute(query)).scalars())
    keys = await projects_service.project_keys(session, {item.project_id for item in items})
    return [
        ItemLinkSearchResult(
            id=item.id,
            number=item.number,
            key=f"{keys[item.project_id]}-{item.number}",
            title=item.title,
            kind=ItemKind(item.kind),
        )
        for item in items
    ]


# --- item links (dependencies) ---


async def _resolve_link_target(
    session: AsyncSession, project: Project, data: ItemLinkCreate
) -> WorkItem:
    """Resolve the link target by id or by per-project number (exactly one required).
    `target_number` means "in the SOURCE item's project" (the bare-number form);
    addressing by `target_id` may cross projects (spec 80)."""
    if data.target_id is not None:
        return await require_item(session, data.target_id)
    if data.target_number is not None:
        target = await session.scalar(
            select(WorkItem).where(
                WorkItem.project_id == project.id, WorkItem.number == data.target_number
            )
        )
        if target is None:
            raise NotFoundError(ItemEntity.ITEM, f"{project.key}-{data.target_number}")
        return target
    raise ConflictError(ItemEntity.LINK, reason="target_id or target_number is required")


async def _check_link_rules(
    session: AsyncSession, source: WorkItem, target: WorkItem, link_type: str, *, symmetric: bool
) -> None:
    if target.id == source.id:
        raise ConflictError(ItemEntity.LINK, reason="an item cannot link to itself")
    # Cross-project links are legal since spec 80 (spec 86: no boundary above).
    duplicate = await session.scalar(
        select(ItemLink.id).where(
            ItemLink.source_item_id == source.id,
            ItemLink.target_item_id == target.id,
            ItemLink.link_type == link_type,
        )
    )
    if duplicate is not None:
        raise ConflictError(ItemEntity.LINK, reason=f"a {link_type} link already exists")
    if symmetric:
        # A symmetric type (e.g. `relates`) reads the same both ways — reject the mirror.
        mirror = await session.scalar(
            select(ItemLink.id).where(
                ItemLink.source_item_id == target.id,
                ItemLink.target_item_id == source.id,
                ItemLink.link_type == link_type,
            )
        )
        if mirror is not None:
            raise ConflictError(ItemEntity.LINK, reason=f"a {link_type} link already exists")


# --- derived mention backlinks (spec 52) ---


async def _resolve_mention_targets(session: AsyncSession, keys: set[str]) -> set[uuid.UUID]:
    """Item ids for the given canonical keys. Unknown keys are silently dropped —
    a `#`-reference to a non-existent item simply produces no backlink."""
    ids: set[uuid.UUID] = set()
    for key in keys:
        item = await find_item_by_key(session, key)
        if item is not None:
            ids.add(item.id)
    return ids


async def sync_mention_links(session: AsyncSession, item: WorkItem) -> None:
    """Reconcile the item's outgoing `mentions` links so they match the item keys
    `#`-referenced in its title + description (spec 52). Derived, so this owns the
    whole set: adds new targets, drops stale ones. Cross-project is allowed and a
    self-mention is skipped. Manual dependency links (blocks/relates/duplicates) and
    other items' mention links are never touched."""
    desired = await _resolve_mention_targets(
        session, parse_issue_keys(f"{item.title}\n{item.description or ''}")
    )
    desired.discard(item.id)
    existing = {
        row.target_item_id: row
        for row in (
            await session.execute(
                select(ItemLink).where(
                    ItemLink.source_item_id == item.id,
                    ItemLink.link_type == ItemLinkType.MENTIONS.value,
                )
            )
        ).scalars()
    }
    for target_id, row in existing.items():
        if target_id not in desired:
            await session.delete(row)
    for target_id in desired - set(existing):
        session.add(
            ItemLink(
                source_item_id=item.id,
                target_item_id=target_id,
                link_type=ItemLinkType.MENTIONS.value,
            )
        )
    await session.flush()


async def add_item_link(
    session: AsyncSession, item_id: uuid.UUID, data: ItemLinkCreate, actor: User
) -> ItemRead:
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    # Validate the link type against the catalog (spec 91): must exist, be manual
    # (not auto-managed like `mentions`), and be in scope for the source project.
    catalog = await linktypes_service.catalog(session)
    definition = catalog.get(data.link_type)
    if definition is None:
        raise ConflictError(ItemEntity.LINK, reason=f"unknown link type '{data.link_type}'")
    if definition.auto_managed:
        raise ConflictError(ItemEntity.LINK, reason=f"{data.link_type} links are managed automatically")
    if definition.project_ids and project.id not in definition.project_ids:
        raise ConflictError(
            ItemEntity.LINK, reason=f"the '{definition.key}' link type isn't available in this project"
        )
    target = await _resolve_link_target(session, project, data)
    await _check_link_rules(
        session, item, target, data.link_type,
        symmetric=linktypes_service.is_symmetric(catalog, data.link_type),
    )
    before = await _hydrate_one(session, item, project, actor, permissions)
    session.add(
        ItemLink(source_item_id=item.id, target_item_id=target.id, link_type=data.link_type)
    )
    await session.flush()
    return await _finish_link(session, item, project, actor, permissions, before=before)


async def remove_item_link(
    session: AsyncSession, item_id: uuid.UUID, link_id: uuid.UUID, actor: User
) -> None:
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    link = await session.get(ItemLink, link_id)
    if link is None or item.id not in (link.source_item_id, link.target_item_id):
        raise NotFoundError(ItemEntity.LINK, link_id)
    before = await _hydrate_one(session, item, project, actor, permissions)
    await session.delete(link)
    await session.flush()
    await _finish_link(session, item, project, actor, permissions, before=before)


async def _finish_link(
    session: AsyncSession,
    item: WorkItem,
    project: Project,
    actor: User,
    permissions: frozenset[Permission],
    *,
    before: ItemRead | None = None,
) -> ItemRead:
    """A link change is an update to the item — re-hydrate + emit item.updated."""
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    return await _finish(
        session, item, project, ItemEvent.UPDATED, actor, ctx, definitions, permissions, before=before
    )
