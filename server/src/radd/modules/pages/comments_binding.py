"""Pages accept comments (RADD-717).

Registered here rather than in `comments`, so the comments module never learns
that pages exist — the same inversion `attachments_binding.py` uses for files.

A page has no PROJECT, so `project_of` returns None — but it does have a SPACE,
and since RADD-791 that is a scope. The checks below resolve against it.

The previous version of this file said the global check "is not a gap in the
model, it is how page atoms are already granted", and that was wrong in a way
worth recording: `comment.write` is a PROJECT-scoped atom, so resolving it at
global scope meant a project-scoped grant never reached it and page commenting
was dead for everyone but an admin or a holder of a global grant. A gate that
consults the wrong scope reads exactly like a gate that works.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.comments.parents import CommentParent, register_parent
from radd.modules.comments.types import CommentParentType

from . import service as pages_service, page_access
from radd.exceptions import NotFoundError
from .types import PageEvent, PageEntity


async def _page_project(session: AsyncSession, page_id: uuid.UUID) -> None:
    """None: a page belongs to no project. The page must EXIST though —
    commenting on a missing page should 404, not create an unreachable thread."""
    await pages_service.get_page(session, page_id)
    return None


async def _space_of(session: AsyncSession, page_id: uuid.UUID) -> uuid.UUID:
    return (await pages_service.get_page(session, page_id)).space_id


async def _page_read(session, user: User, page_id: uuid.UUID, project):
    del project  # a page has no project; its space is the scope (RADD-791)
    page = await pages_service.get_page(session, page_id)
    permissions = await authz.require(session, user, Permission.PAGE_READ, space_id=page.space_id)
    if not await page_access.page_access(session, user, page):
        raise NotFoundError(PageEntity.PAGE, page_id)
    return permissions


async def _page_write(session, user: User, page_id: uuid.UUID, project):
    """Reading the page plus the ordinary comment atom, both IN ITS SPACE.
    Writing a page is NOT required — the point of a page discussion is that
    people who cannot edit the page can still argue about it. Which is precisely
    what did not work while these resolved globally (RADD-791)."""
    del project
    space_id = await _space_of(session, page_id)
    await _page_read(session, user, page_id, None)
    return await authz.require(session, user, Permission.COMMENT_WRITE, space_id=space_id)


register_parent(
    CommentParent(
        entity_type=CommentParentType.PAGE.value,
        deleted_event=PageEvent.PAGE_DELETED.value,
        project_of=_page_project,
        require_read=_page_read,
        require_write=_page_write,
        # Editing or removing someone else's page comment is a wiki-admin act.
        manage_permission=Permission.PAGE_MANAGE,
    )
)
