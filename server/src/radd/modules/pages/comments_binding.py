"""Pages accept comments (RADD-717).

Registered here rather than in `comments`, so the comments module never learns
that pages exist — the same inversion `attachments_binding.py` uses for files.

A page is GLOBAL: it has no project, so `project_of` returns None and every
check below runs at global scope. That is not a gap in the model, it is how page
atoms are already granted.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.comments.parents import CommentParent, register_parent
from radd.modules.comments.types import CommentParentType

from . import service as pages_service
from .types import PageEvent


async def _page_project(session: AsyncSession, page_id: uuid.UUID) -> None:
    """None: pages are global. The page must EXIST though — commenting on a
    missing page should 404, not create an unreachable thread."""
    await pages_service.get_page(session, page_id)
    return None


async def _page_read(session, user: User, page_id: uuid.UUID, project):
    return await authz.require(session, user, Permission.PAGE_READ, project=project)


async def _page_write(session, user: User, page_id: uuid.UUID, project):
    """Reading the page plus the ordinary comment atom. Writing a page is NOT
    required — the point of a page discussion is that people who cannot edit the
    page can still argue about it."""
    await authz.require(session, user, Permission.PAGE_READ, project=project)
    return await authz.require(session, user, Permission.COMMENT_WRITE, project=project)


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
