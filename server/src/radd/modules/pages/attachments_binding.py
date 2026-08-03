"""The page attachment parent (spec 102): wiki pages own files.

Registered from the docs plugin so `attachments` never learns this module
exists (its ParentBinding registry is the seam). `project_id_of` is None — a
wiki file has no project for attachment routing/ACL context — but the page's
SPACE is a scope since RADD-791, and that is what the guards below resolve
against, so "who may attach in the render space" is an ordinary role grant.

Known follow-up (documented in the spec): PUBLIC kb spaces render without a
session, but downloads require one — public pages need a public mint path on
`public_router` before images work there.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.attachments import parents
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission

from .types import PageEvent
from radd.modules.auth.models import User

from . import service


async def _guard(
    session: AsyncSession, user: User, page_id: uuid.UUID, permission: Permission
) -> None:
    page = await service.get_page(session, page_id)  # 404 before 403, like the router
    await authz.require(session, user, permission, space_id=page.space_id)


async def _page_read(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await _guard(session, user, page_id, Permission.PAGE_READ)


async def _page_write(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await _guard(session, user, page_id, Permission.PAGE_WRITE)


async def _page_admin(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await _guard(session, user, page_id, Permission.PAGE_MANAGE)


async def _no_project(session: AsyncSession, page_id: uuid.UUID) -> uuid.UUID | None:
    return None


parents.register_parent(
    parents.ParentBinding(
        entity_type=AttachmentParentType.PAGE.value,
        deleted_event=PageEvent.PAGE_DELETED.value,
        require_read=_page_read,
        require_write=_page_write,
        require_admin=_page_admin,
        project_id_of=_no_project,
    )
)
