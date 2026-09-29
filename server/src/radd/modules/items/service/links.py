"""Item links: dependency typeahead, manual links, derived mention backlinks."""

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields
from radd.modules.linktypes import service as linktypes_service
from radd.modules.linktypes.types import ItemLinkType
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from ..enums import ItemEntity, ItemEvent, ItemKind
from .visibility import relation_read_clause
from ..mentions import parse_issue_keys
from ..models import ItemKeyAlias, ItemLink, WorkItem
from ..schemas import ItemLinkCreate, ItemLinkSearchResult, ItemRead
from .queries import _parse_key, find_item_by_key, require_item_permission, require_readable_item
from .read import _finish, _hydrate_one
from .visibility import _field_ctx


# --- link typeahead (dependency add-row autocomplete) ---


def _search_number(term: str) -> int | None:
    """Pull an item number from a search term: '23' or 'TD-23' -> 23, else None."""
    candidate = term.rsplit("-", 1)[1] if "-" in term else term
    return int(candidate) if candidate.isdigit() else None


def _named_key_clause(project_key: str, number: int, term: str):
    """The row a full key names: `number` in the project whose key is
    `project_key`, or the item a spec-68 alias for `term` still points at."""
    in_named_project = WorkItem.project_id.in_(
        select(Project.id).where(Project.key == project_key.upper())
    )
    aliased = WorkItem.id.in_(
        select(ItemKeyAlias.item_id).where(ItemKeyAlias.old_key == term.upper())
    )
    return or_(and_(in_named_project, WorkItem.number == number), aliased)


async def link_search(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    q: str,
    actor: User,
    limit: int = 8,
    exclude_id: uuid.UUID | None = None,
    kind: ItemKind | None = None,
    unparented: bool = False,
) -> list[ItemLinkSearchResult]:
    """Typeahead candidates for a dependency link or parent pick: items across
    every project the actor can read (spec 80/86 — no boundary above that)
    matching `q` by title substring or number/key. Same-project matches
    rank first, newest-numbered within each tier. `exclude_id` drops the item
    being linked from (no self-link). `kind` narrows to one kind — the parent
    picker asks for the kind the ladder requires, so the LIMIT is spent on
    candidates that can be picked (RADD-1472). `unparented` keeps only items
    with no parent — an epic adopting existing issues (RADD-1473)."""
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
    if kind is not None:
        query = query.where(WorkItem.kind == kind.value)
    if unparented:
        query = query.where(WorkItem.parent_id.is_(None))
    term = q.strip()
    tiers = [(WorkItem.project_id == project_id).desc(), WorkItem.number.desc()]
    if term:
        conditions = [WorkItem.title.ilike(ilike_term(term))]
        number = _search_number(term)
        if number is not None:
            conditions.append(WorkItem.number == number)
        parsed = _parse_key(term)
        if parsed is not None:
            # A full key names ITS project (RADD-1490): `DEV-23` typed on a TD item
            # means DEV-23, so that row (or the row a spec-68 alias points at)
            # leads the list ahead of the anchor project's own 23.
            named = _named_key_clause(parsed[0], parsed[1], term)
            conditions.append(named)
            tiers.insert(0, named.desc())
        query = query.where(or_(*conditions))
    # Tiered ordering (spec 80): the named key, then the anchor project's own items.
    query = query.order_by(*tiers).limit(limit)
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
    session: AsyncSession, project: Project, data: ItemLinkCreate, actor: User
) -> WorkItem:
    """Resolve the link target by id, by full key or by per-project number
    (exactly one required). `target_key` resolves in the project the key NAMES,
    aliases included (RADD-1490); `target_number` means "in the SOURCE item's
    project" (the bare-number form); `target_id` may cross projects (spec 80).
    Either way the target goes through the read seam (RADD-1455): one the actor
    cannot see answers exactly as a missing one, so a link is no existence oracle."""
    given = [
        f for f in ("target_id", "target_key", "target_number") if getattr(data, f) is not None
    ]
    if len(given) > 1:
        raise ConflictError(ItemEntity.LINK, reason="address the target one way, not several")
    if data.target_id is not None:
        target, _project, _permissions = await require_readable_item(session, data.target_id, actor)
        return target
    if data.target_key is not None:
        found = await find_item_by_key(session, data.target_key)
        if found is None:
            raise NotFoundError(ItemEntity.ITEM, data.target_key)
        try:
            target, _project, _permissions = await require_readable_item(session, found.id, actor)
        except NotFoundError:
            raise NotFoundError(ItemEntity.ITEM, data.target_key) from None
        return target
    if data.target_number is not None:
        key = f"{project.key}-{data.target_number}"
        target_id = await session.scalar(
            select(WorkItem.id).where(
                WorkItem.project_id == project.id, WorkItem.number == data.target_number
            )
        )
        if target_id is None:
            raise NotFoundError(ItemEntity.ITEM, key)
        try:
            target, _project, _permissions = await require_readable_item(session, target_id, actor)
        except NotFoundError:
            raise NotFoundError(ItemEntity.ITEM, key) from None
        return target
    raise ConflictError(
        ItemEntity.LINK, reason="target_id, target_key or target_number is required"
    )


async def _check_link_rules(
    session: AsyncSession, source: WorkItem, target: WorkItem, link_type: str, *, symmetric: bool
) -> None:
    if target.id == source.id:
        raise ConflictError(ItemEntity.LINK, reason="an item cannot link to itself")
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
    item, project, permissions = await require_item_permission(
        session, item_id, actor, Permission.ITEM_UPDATE
    )
    # Validate the link type against the catalog (spec 91): must exist, be manual
    # (not auto-managed like `mentions`), and be in scope for the source project.
    catalog = await linktypes_service.catalog(session)
    definition = catalog.get(data.link_type)
    if definition is None:
        raise ConflictError(ItemEntity.LINK, reason=f"unknown link type '{data.link_type}'")
    if definition.auto_managed:
        raise ConflictError(
            ItemEntity.LINK, reason=f"{data.link_type} links are managed automatically"
        )
    if definition.project_ids and project.id not in definition.project_ids:
        raise ConflictError(
            ItemEntity.LINK,
            reason=f"the '{definition.key}' link type isn't available in this project",
        )
    target = await _resolve_link_target(session, project, data, actor)
    await _check_link_rules(
        session,
        item,
        target,
        data.link_type,
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
    item, project, permissions = await require_item_permission(
        session, item_id, actor, Permission.ITEM_UPDATE
    )
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
        session,
        item,
        project,
        ItemEvent.UPDATED,
        actor,
        ctx,
        definitions,
        permissions,
        before=before,
    )
