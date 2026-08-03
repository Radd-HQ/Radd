"""Per-PAGE restriction, on the spec-92 access framework (RADD-792).

The space decides the default (RADD-791). Some pages need to be narrower than
their space — a salary band inside an open HR space.

Hussein's framing, and it is the right one: a page behaves like a custom FIELD.
Unrestricted, it is visible to everyone with access to the space; the moment it
carries a restriction, only the people named on it can reach it. That is exactly
`default_open` in `access/resolution.py`, which custom fields already use — so
this is a `ResourceSpec` registration, not a new mechanism.

## The two layers compose, and the order matters

    SPACE  decides whether you are in the room at all   (a role grant)
    PAGE   can only NARROW within it                    (an access grant)

A page grant never WIDENS past the space. Someone with no access to the space
cannot be let into one page by a grant on it — otherwise the space boundary
would be advisory, and "restrict this page" would become a way to hand out
access to a space you were never given.

`hierarchical` on the spec is about ordered access LEVELS (viewer<editor<owner),
NOT the page tree. Child pages do not inherit a parent's restriction; that is a
tree-level affordance nobody has asked for yet, and guessing at it would mean
someone finds their subtree quietly invisible.
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


_PAGE_SPEC = ResourceSpec(
    resource_type=PAGE_RESOURCE,
    can_manage=_can_manage_page,
    accesses=(Access.READ.value, Access.WRITE.value),
    # Open until restricted — the custom-field model, which is what Hussein
    # asked for and what makes an unrestricted wiki behave exactly as before.
    default_open=True,
    implied_by={Access.READ.value: (Access.WRITE.value,)},  # a writer can read
    subjects=(GrantSubject.USER, GrantSubject.TEAM, GrantSubject.ROLE),
    # A page belongs to a SPACE, not a project, so grants carry no project scope.
    project_scoped=False,
    label="Page",
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
    from radd.modules.teams import service as teams_service

    return SubjectContext(
        user_id=user.id,
        role_ids=frozenset(
            await role_grants.granted_role_ids(session, user.id, space_id=space_id)
        ),
        team_ids=frozenset(await teams_service.user_team_ids(session, user.id)),
        has_manage=can_manage,
    )


async def page_access(
    session: AsyncSession, user: User, page: Page, access: str = Access.READ.value
) -> bool:
    """May this actor read (or write) this ONE page?

    Space first, page second — and the page half can only take access away.
    """
    space_held = await space_access.space_permissions(session, user, page.space_id)
    needed = Permission.PAGE_READ if access == Access.READ.value else Permission.PAGE_WRITE
    if needed not in space_held:
        return False
    grants = await access_service.list_for_resource(session, PAGE_RESOURCE, str(page.id))
    if not grants:
        return True  # unrestricted: the space's answer stands
    ctx = await _subject_context(
        session, user, page.space_id, can_manage=Permission.PAGE_MANAGE in space_held
    )
    return has_access(grants, ctx, access, None, _PAGE_SPEC)


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
    space_ids = {page.space_id for page in pages}
    space_perms = await space_access.permissions_by_space(session, user, list(space_ids))
    grants_by_page = await access_service.grants_for_resources(
        session, PAGE_RESOURCE, [str(page.id) for page in pages]
    )
    contexts: dict[uuid.UUID, SubjectContext] = {}
    readable: set[uuid.UUID] = set()
    for page in pages:
        held = space_perms.get(page.space_id, frozenset())
        if Permission.PAGE_READ not in held:
            continue
        grants = grants_by_page.get(str(page.id)) or []
        if not grants:
            readable.add(page.id)
            continue
        if page.space_id not in contexts:
            contexts[page.space_id] = await _subject_context(
                session, user, page.space_id, can_manage=Permission.PAGE_MANAGE in held
            )
        if has_access(grants, contexts[page.space_id], Access.READ.value, None, _PAGE_SPEC):
            readable.add(page.id)
    return readable


async def restricted_page_ids(
    session: AsyncSession, page_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of these pages carry ANY restriction — drives the padlock in the UI."""
    if not page_ids:
        return set()
    grants = await access_service.grants_for_resources(
        session, PAGE_RESOURCE, [str(page_id) for page_id in page_ids]
    )
    return {uuid.UUID(rid) for rid, rows in grants.items() if rows}
