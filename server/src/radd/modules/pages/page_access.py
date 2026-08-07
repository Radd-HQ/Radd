"""Per-PAGE restriction, on the spec-92 access framework (RADD-792).

The space decides the default (RADD-791). Some pages need to be narrower than
their space — a salary band inside an open HR space.

Hussein's framing, and it is the right one: a page behaves like a custom FIELD.
Unrestricted, it is visible to everyone with access to the space; the moment it
carries a restriction, only the people named on it can reach it. That is exactly
`default_open` in `access/resolution.py`, which custom fields already use — so
this is a `ResourceSpec` registration, not a new mechanism.

## The three layers compose, and the order matters

    SPACE  decides whether you are in the room at all   (a role grant)
    PATH   every restriction from the root down to here (RADD-948)
    PAGE   its own                                      (an access grant)

A page grant never WIDENS past the space. Someone with no access to the space
cannot be let into one page by a grant on it — otherwise the space boundary
would be advisory, and "restrict this page" would become a way to hand out
access to a space you were never given.

**And a restriction runs down the tree** (RADD-948). Every grant set on the
ancestor path must pass, plus the page's own. RADD-792 shipped the opposite —
"child pages do not inherit a parent's restriction; guessing at it would mean
someone finds their subtree quietly invisible" — and that traded a subtree
quietly INVISIBLE for a subtree quietly VISIBLE, which is the worse of the two
by a wide margin. Sensitive material is naturally written as a parent page with
children, so leaving children open was the default outcome, not the edge case.

It is deliberately every ancestor rather than the nearest one. Nearest-wins lets
a child re-open what its parent closed: put any grant on the child and someone
excluded above reaches it by search or direct link — the same hole, one level
down, and exactly what the space rule already forbids. Access may only narrow as
you descend.

`hierarchical` on the spec is unrelated: it means ordered access LEVELS
(viewer<editor<owner), not the page tree.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.access import service as access_service
from radd.modules.access.registry import ResourceSpec, register_resource
from radd.modules.access.resolution import SubjectContext, has_access
from radd.modules.access.types import Access, GrantSubject
from radd.modules.auth import grants as role_grants
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User

from . import access as space_access
from .models import Page

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
    from sqlalchemy import select

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


_PAGE_SPEC = ResourceSpec(
    resource_type=PAGE_RESOURCE,
    can_manage=_can_manage_page,
    accesses=(Access.READ.value, Access.WRITE.value),
    # Open until restricted — the custom-field model, which is what Hussein
    # asked for and what makes an unrestricted wiki behave exactly as before.
    default_open=True,
    implied_by={Access.READ.value: (Access.WRITE.value,)},  # a writer can read
    subjects=(GrantSubject.USER, GrantSubject.TEAM, GrantSubject.ROLE, GrantSubject.GROUP),
    # A page belongs to a SPACE, not a project, so grants carry no project scope.
    project_scoped=False,
    label="Page",
    label_for=_page_labels,
)
register_resource(_PAGE_SPEC)


async def _subject_context(
    session: AsyncSession, user: User, space_id: uuid.UUID, *, can_manage: bool
) -> SubjectContext:
    """What the actor brings to a page grant.

    `role_ids` are the roles they hold IN THE SPACE — the space equivalent of
    "roles held on this project" — so a grant naming a role means what a reader
    would expect: the people who hold that role here.
    """
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
    """`page` and every ancestor above it, nearest first.

    Bounded by a seen-set rather than trusting the tree: `core.would_create_cycle`
    guards the write path, but a loop already in the data must read as a finite
    path, not hang the request (the same defence `test_pages` pins for moves).
    """
    from sqlalchemy import select

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
    """May this actor read (or write) this page?

    Space first, then every restriction on the path down to it — each layer can
    only take access away.
    """
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
        # The resource-owned manager rule (RADD-816 moved it here from the
        # framework): a space's page.manage holder administers restrictions,
        # so they can always see what they administer. Named at the call site,
        # never a framework bypass.
        return True
    ctx = await _subject_context(session, user, page.space_id, can_manage=False)
    return all(has_access(grants, ctx, access, None, _PAGE_SPEC) for grants in restricted)


async def readable_page_ids(
    session: AsyncSession, user: User, pages: list[Page]
) -> set[uuid.UUID]:
    """Batched `page_access` over a list — the page tree, FTS results, a label index.

    Filtering these matters more than it looks: a restricted page whose TITLE
    still surfaced in search would defeat the restriction entirely, since a page
    title is usually the sensitive part.
    """
    if not pages:
        return set()
    from sqlalchemy import select

    space_ids = {page.space_id for page in pages}
    space_perms = await space_access.permissions_by_space(session, user, list(space_ids))

    # The parent map for every involved space, in ONE query (RADD-948). An
    # ancestor is usually NOT in `pages` — FTS returns matches, not their
    # lineage — so the path cannot be resolved from the input alone. Ids and
    # parents only: no bodies, no titles.
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
