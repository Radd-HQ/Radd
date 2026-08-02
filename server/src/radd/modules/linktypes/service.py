"""Issue link types: the catalog + CRUD + scope (spec 91).

The single source of truth for what link relationships exist. `items` resolves a
link's directional label and symmetry through this seam (never a hardcoded enum),
so a custom type behaves exactly like a built-in one. Built-ins are seeded on
startup; their keys/direction are locked so existing links + SLQ keep working.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service

from .models import LinkTypeDef, LinkTypeProject
from .schemas import LinkTypeCreate, LinkTypeUpdate
from .types import BUILTIN_LINK_TYPES, LinkDirection, LinkTypeEntity, LinkTypeEvent


# --- queries ------------------------------------------------------------------


async def list_types(session: AsyncSession) -> list[LinkTypeDef]:
    result = await session.execute(select(LinkTypeDef).order_by(LinkTypeDef.created_at))
    return list(result.scalars())


async def get_type(session: AsyncSession, type_id: uuid.UUID) -> LinkTypeDef:
    definition = await session.get(LinkTypeDef, type_id)
    if definition is None:
        raise NotFoundError(LinkTypeEntity.LINK_TYPE, type_id)
    return definition


async def by_key(session: AsyncSession, key: str) -> LinkTypeDef | None:
    return await session.scalar(select(LinkTypeDef).where(LinkTypeDef.key == key))


async def catalog(session: AsyncSession) -> dict[str, LinkTypeDef]:
    """key → definition, for hydration/validation (a handful of rows)."""
    return {t.key: t for t in await list_types(session)}


async def types_for_project(
    session: AsyncSession, project_id: uuid.UUID, *, include_auto: bool = False
) -> list[LinkTypeDef]:
    """The manual link types offered on an item in a project: global ones (no scope
    rows) plus those scoped to this project. Auto-managed types (mentions) are
    excluded from the manual picker unless asked for."""
    scoped_to_project = select(LinkTypeProject.link_type_id).where(
        LinkTypeProject.project_id == project_id
    )
    query = select(LinkTypeDef).where(
        LinkTypeDef.id.not_in(select(LinkTypeProject.link_type_id))
        | LinkTypeDef.id.in_(scoped_to_project)
    )
    if not include_auto:
        query = query.where(LinkTypeDef.auto_managed.is_(False))
    return list((await session.execute(query.order_by(LinkTypeDef.created_at))).scalars())


async def usage_counts(session: AsyncSession) -> dict[str, int]:
    """link_type key → number of links using it (the Usages column)."""
    from radd.modules.items.models import ItemLink  # deferred: items loads after linktypes

    rows = await session.execute(
        select(ItemLink.link_type, func.count()).group_by(ItemLink.link_type)
    )
    return {key: count for key, count in rows.all()}


async def resolve_by_name(session: AsyncSession, name: str | None) -> str | None:
    """A Jira link-type NAME → a Radd type key, matched case-insensitively against a
    type's name/outward/inward names (spec 91 importer integration). None if no
    match — the caller falls back to a default."""
    if not name:
        return None
    needle = name.strip().casefold()
    for t in await list_types(session):
        if needle in {t.name.casefold(), t.outward_name.casefold(), t.inward_name.casefold()}:
            return t.key
    return None


# --- pure predicates over a catalog (used by items) ---------------------------


def is_symmetric(catalog_by_key: dict[str, LinkTypeDef], key: str) -> bool:
    definition = catalog_by_key.get(key)
    return definition is not None and definition.direction == LinkDirection.SYMMETRIC


def is_auto_managed(catalog_by_key: dict[str, LinkTypeDef], key: str) -> bool:
    definition = catalog_by_key.get(key)
    return definition is not None and definition.auto_managed


def label_for(definition: LinkTypeDef | None, *, incoming: bool) -> str:
    """The directional display name for one edge: inward when THIS item is the
    target, outward when it is the source. Falls back to the raw key."""
    if definition is None:
        return "relates to"
    return definition.inward_name if incoming else definition.outward_name


# --- CRUD ---------------------------------------------------------------------


async def _validate_projects(session: AsyncSession, project_ids: list[uuid.UUID]) -> None:
    for project_id in project_ids:
        await projects_service.get_project(session, project_id)


async def create_type(
    session: AsyncSession, data: LinkTypeCreate, actor_id: uuid.UUID | None = None
) -> LinkTypeDef:
    if await by_key(session, data.key):
        raise ConflictError(LinkTypeEntity.LINK_TYPE, data.key)
    await _validate_projects(session, data.project_ids)
    definition = LinkTypeDef(
        key=data.key,
        name=data.name,
        outward_name=data.outward_name,
        inward_name=data.inward_name,
        direction=data.direction.value,
        system=False,
        auto_managed=False,
        project_links=[LinkTypeProject(project_id=pid) for pid in data.project_ids],
    )
    session.add(definition)
    await session.flush()
    await _emit(session, LinkTypeEvent.CREATED, definition, actor_id)
    return definition


async def update_type(
    session: AsyncSession, type_id: uuid.UUID, data: LinkTypeUpdate, actor_id: uuid.UUID | None = None
) -> LinkTypeDef:
    definition = await get_type(session, type_id)
    if data.name is not None:
        definition.name = data.name
    if data.outward_name is not None:
        definition.outward_name = data.outward_name
    if data.inward_name is not None:
        definition.inward_name = data.inward_name
    if data.direction is not None:
        if definition.system:
            raise ConflictError(
                LinkTypeEntity.LINK_TYPE, reason="a built-in type's direction is locked"
            )
        definition.direction = data.direction.value
    # A symmetric type reads the same both ways — keep the names in sync.
    if definition.direction == LinkDirection.SYMMETRIC.value:
        definition.inward_name = definition.outward_name
    if data.project_ids is not None:
        await _validate_projects(session, data.project_ids)
        wanted = list(dict.fromkeys(data.project_ids))
        definition.project_links = [LinkTypeProject(project_id=pid) for pid in wanted]
    await session.flush()
    await _emit(session, LinkTypeEvent.UPDATED, definition, actor_id)
    return definition


async def delete_type(
    session: AsyncSession, type_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    definition = await get_type(session, type_id)
    if definition.system:
        raise ConflictError(LinkTypeEntity.LINK_TYPE, reason="a built-in type can't be deleted")
    usages = (await usage_counts(session)).get(definition.key, 0)
    if usages:
        raise ConflictError(
            LinkTypeEntity.LINK_TYPE, reason=f"{usages} link(s) still use this type"
        )
    await _emit(session, LinkTypeEvent.DELETED, definition, actor_id)
    await session.delete(definition)
    await session.flush()


async def _emit(
    session: AsyncSession, event: LinkTypeEvent, definition: LinkTypeDef, actor_id: uuid.UUID | None
) -> None:
    await events.emit(
        session,
        event_type=event,
        entity_type=LinkTypeEntity.LINK_TYPE,
        entity_id=definition.id,
        actor_id=actor_id,
        payload={"key": definition.key, "name": definition.name},
    )


# --- startup seed -------------------------------------------------------------


async def ensure_builtins() -> None:
    """Seed the built-in link types if missing (idempotent). Existing links already
    carry these keys, so this only fills the catalog rows that describe them."""
    from radd.db import SessionLocal

    async with SessionLocal() as session:
        existing = {t.key for t in await list_types(session)}
        created = False
        for spec in BUILTIN_LINK_TYPES:
            if spec["key"] in existing:
                continue
            session.add(
                LinkTypeDef(
                    key=spec["key"],
                    name=spec["name"],
                    outward_name=spec["outward_name"],
                    inward_name=spec["inward_name"],
                    direction=spec["direction"].value,
                    system=spec["system"],
                    auto_managed=spec["auto_managed"],
                )
            )
            created = True
        if created:
            await session.commit()
