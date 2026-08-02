"""The doc_page attachment parent (spec 102): wiki pages own files.

Registered from the docs plugin so `attachments` never learns this module
exists (its ParentBinding registry is the seam). Doc permissions are global
atoms, so `project_id_of` is None — attachment routing/ACL context for a wiki
file has no project.

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
from radd.modules.auth.models import User

from . import service


async def _page_read(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await service.get_page(session, page_id)  # 404 before 403, like the doc router
    await authz.require(session, user, Permission.DOC_READ)


async def _page_write(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await service.get_page(session, page_id)
    await authz.require(session, user, Permission.DOC_WRITE)


async def _page_admin(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await service.get_page(session, page_id)
    await authz.require(session, user, Permission.DOC_MANAGE)


async def _no_project(session: AsyncSession, page_id: uuid.UUID) -> uuid.UUID | None:
    return None


parents.register_parent(
    parents.ParentBinding(
        entity_type=AttachmentParentType.DOC_PAGE.value,
        require_read=_page_read,
        require_write=_page_write,
        require_admin=_page_admin,
        project_id_of=_no_project,
    )
)
