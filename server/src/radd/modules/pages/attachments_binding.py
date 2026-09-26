"""The page attachment parent (spec 102), registered here so `attachments` never
learns pages exist. No project; the SPACE is the scope (RADD-791)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.attachments import parents
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth.authz import Permission

from .types import PageEvent
from radd.modules.auth.models import User

from . import service, page_access


async def _guard(
    session: AsyncSession, user: User, page_id: uuid.UUID, permission: Permission
) -> None:
    await page_access.guard_page(session, user, page_id, permission)


async def _page_read(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await _guard(session, user, page_id, Permission.PAGE_READ)


async def _page_write(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await _guard(session, user, page_id, Permission.PAGE_WRITE)


async def _page_admin(session: AsyncSession, user: User, page_id: uuid.UUID) -> None:
    await _guard(session, user, page_id, Permission.PAGE_MANAGE)


async def _no_project(session: AsyncSession, page_id: uuid.UUID) -> uuid.UUID | None:
    return None


async def _space_id(session: AsyncSession, page_id: uuid.UUID) -> uuid.UUID:
    return (await service.get_page(session, page_id)).space_id


parents.register_parent(
    parents.ParentBinding(
        entity_type=AttachmentParentType.PAGE.value,
        deleted_event=PageEvent.PAGE_DELETED.value,
        require_read=_page_read,
        require_write=_page_write,
        require_admin=_page_admin,
        project_id_of=_no_project,
        space_id_of=_space_id,
    )
)
