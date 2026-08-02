import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import service
from .schemas import MailContactRead
from .types import MailEntity

router = APIRouter(tags=["mailintake"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/items/{item_id}/mail-contact", response_model=MailContactRead)
async def item_mail_contact(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> MailContactRead:
    """The item's external requester (spec 62) — 404 when the item has none
    (most items: anything raised by a registered user)."""
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, Permission.ITEM_READ, project=project)
    contact = await service.contact_for_item(session, item_id)
    if contact is None:
        raise NotFoundError(MailEntity.CONTACT, item_id)
    return MailContactRead.model_validate(contact)
