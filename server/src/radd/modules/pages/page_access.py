"""Per-PAGE restriction on the spec-92 access framework (RADD-792/948).

Three layers, each of which can only NARROW access:

    SPACE  whether you are in the room at all   (a role grant)
    PATH   every restriction from the root down (RADD-948)
    PAGE   its own                               (an access grant)

An unrestricted page is open to everyone in the space (`default_open`, the
custom-field model). A page grant never widens past the space, and EVERY
ancestor's restriction applies — nearest-wins would let a child re-open what
its parent closed. `hierarchical` on the spec means access LEVELS, not the tree.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.access import service as access_service
from radd.modules.access.registry import ResourceSpec, register_resource
from radd.modules.access.resolution import SubjectContext, has_access
from radd.modules.access.types import Access, GrantSubject
from radd.exceptions import NotFoundError
from radd.modules.auth import authz, grants as role_grants
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User

from . import access as space_access
from .models import Page
from .types import PageEntity

PAGE_RESOURCE = "page"


async def _can_manage_page(
    session: AsyncSession, actor: User, resource_id: str, project_id: uuid.UUID | None
) -> bool:
    """Restricting a page is a wiki-admin act IN ITS SPACE: `page.manage` there."""
    del project_id  # a page has no project; its space is the scope
    from . import service as pages_service

    try:
        page = await pages_service.get_page(session, uuid.UUID(resource_id))
    except Exception:  # noqa: BLE001 — a bad id is "no", not a 500
        return False
    held = await space_access.space_permissions(session, actor, page.space_id)
    return Permission.PAGE_MANAGE in held


async def _page_labels(session: AsyncSession, resource_ids) -> dict[str, str]:
    """Inspector labels (RADD-809): page id -> title."""
    ids = []
    for raw in resource_ids:
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = await session.execute(select(Page.id, Page.title).where(Page.id.in_(ids)))
    return {str(page_id): title for page_id, title in rows.all()}


async def _roles_for_page(session, user_id, resource_id):
    from .service import get_page
    page = await get_page(session, uuid.UUID(resource_id))
    return await role_grants.granted_role_ids(session, user_id, space_id=page.space_id)


_PAGE_SPEC = ResourceSpec(
    resource_type=PAGE_RESOURCE,
    can_manage=_can_manage_page,
    accesses=(Access.READ.value, Access.WRITE.value),
    # Open until restricted — the custom-field model.
    default_open=True,
    implied_by={Access.READ.value: (Access.WRITE.value,)},  # a writer can read
    subjects=(GrantSubject.USER, GrantSubject.TEAM, GrantSubject.ROLE, GrantSubject.GROUP),
    # A page belongs to a SPACE, not a project, so grants carry no project scope.
    project_scoped=False,
    label="Page",
    label_for=_page_labels,
    roles_for=_roles_for_page,
)
register_resource(_PAGE_SPEC)


async def _subject_context(
    session: AsyncSession, user: User, space_id: uuid.UUID, *, can_manage: bool
) -> SubjectContext:
    """What the actor brings to a page grant; `role_ids` are the roles held IN
    THE SPACE, so a grant naming a role means the people who hold it here."""
    from radd.modules.groups import service as groups_service
    from radd.modules.teams import service as teams_service

    return SubjectContext(
        user_id=user.id,
        role_ids=frozenset(
            await role_grants.granted_role_ids(session, user.id, space_id=space_id)
        ),
        team_ids=frozenset(await teams_service.user_team_ids(session, user.id)),
        group_ids=frozenset(await groups_service.user_group_ids(session, user.id)),
        has_manage=can_manage,
    )


async def _ancestor_path(session: AsyncSession, page: Page) -> list[uuid.UUID]:
    """`page` and every ancestor, nearest first. A seen-set bounds it: a loop
    already in the data must read as a finite path, not hang the request."""
    chain = [page.id]
    seen = {page.id}
    parent_id = page.parent_id
    while parent_id is not None and parent_id not in seen:
        chain.append(parent_id)
        seen.add(parent_id)
        parent_id = await session.scalar(select(Page.parent_id).where(Page.id == parent_id))
    return chain


async def page_access(
    session: AsyncSession, user: User, page: Page, access: str = Access.READ.value
) -> bool:
    """May this actor read (or write) this page? Space first, then every
    restriction on the path down to it."""
    space_held = await space_access.space_permissions(session, user, page.space_id)
    needed = Permission.PAGE_READ if access == Access.READ.value else Permission.PAGE_WRITE
    if needed not in space_held:
        return False
    path = await _ancestor_path(session, page)
    grants_by_page = await access_service.grants_for_resources(
        session, PAGE_RESOURCE, [str(page_id) for page_id in path]
    )
    restricted = [grants for grants in (grants_by_page.get(str(p)) for p in path) if grants]
    if not restricted:
        return True  # nothing on the path: the space's answer stands
    if Permission.PAGE_MANAGE in space_held:
        # The resource-owned manager rule (RADD-816): a space's page.manage
        # holder always sees what they administer.
        return True
    ctx = await _subject_context(session, user, page.space_id, can_manage=False)
    return all(has_access(grants, ctx, access, None, _PAGE_SPEC) for grants in restricted)


async def guard_page(
    session: AsyncSession, user: User, page_id: uuid.UUID, permission: Permission
) -> Page:
    """Resolve a page and enforce the atom IN ITS SPACE (RADD-791), then the
    page's own restriction (RADD-792) — the one gate every per-page REST route
    and MCP tool goes through."""
    from .service import get_page  # deferred: service imports this module

    page = await get_page(session, page_id)
    await authz.require(session, user, permission, space_id=page.space_id)
    wanted = Access.WRITE.value if permission is not Permission.PAGE_READ else Access.READ.value
    if not await page_access(session, user, page, wanted):
        raise NotFoundError(PageEntity.PAGE, page_id)
    return page


async def readable_page_ids(
    session: AsyncSession, user: User, pages: list[Page]
) -> set[uuid.UUID]:
    """Batched `page_access` over a list — the tree, FTS results, a label index."""
    if not pages:
        return set()
    space_ids = {page.space_id for page in pages}
    space_perms = await space_access.permissions_by_space(session, user, list(space_ids))

    # One parent-map query for every involved space (RADD-948): an ancestor is
    # usually NOT in `pages` (FTS returns matches, not their lineage).
    parent_of: dict[uuid.UUID, uuid.UUID | None] = dict(
        (
            await session.execute(
                select(Page.id, Page.parent_id).where(Page.space_id.in_(space_ids))
            )
        ).all()
    )

    def path_of(page_id: uuid.UUID) -> list[uuid.UUID]:
        chain = [page_id]
        seen = {page_id}
        parent = parent_of.get(page_id)
        while parent is not None and parent not in seen:  # loop-safe, see _ancestor_path
            chain.append(parent)
            seen.add(parent)
            parent = parent_of.get(parent)
        return chain

    paths = {page.id: path_of(page.id) for page in pages}
    grants_by_page = await access_service.grants_for_resources(
        session,
        PAGE_RESOURCE,
        [str(page_id) for path in paths.values() for page_id in path],
    )
    contexts: dict[uuid.UUID, SubjectContext] = {}
    readable: set[uuid.UUID] = set()
    for page in pages:
        held = space_perms.get(page.space_id, frozenset())
        if Permission.PAGE_READ not in held:
            continue
        restricted = [
            grants
            for grants in (grants_by_page.get(str(p)) for p in paths[page.id])
            if grants
        ]
        if not restricted:
            readable.add(page.id)
            continue
        if Permission.PAGE_MANAGE in held:
            readable.add(page.id)  # the resource-owned manager rule (see page_access)
            continue
        if page.space_id not in contexts:
            contexts[page.space_id] = await _subject_context(
                session, user, page.space_id, can_manage=False
            )
        ctx = contexts[page.space_id]
        if all(has_access(g, ctx, Access.READ.value, None, _PAGE_SPEC) for g in restricted):
            readable.add(page.id)
    return readable


async def drop_restricted(session: AsyncSession, actor: User, rows: list, key: str) -> list:
    """`rows` minus the pages `actor` may not read; each row names its page by the
    attribute `key`. List surfaces leak a restriction cheapest: an FTS hit's
    title and snippet ARE the content, and `radd:label-list` renders into a page
    anyone in the space can open."""
    if not rows:
        return rows
    ids = [getattr(row, key) for row in rows]
    pages = list((await session.execute(select(Page).where(Page.id.in_(ids)))).scalars())
    readable = await readable_page_ids(session, actor, pages)
    return [row for row in rows if getattr(row, key) in readable]
