"""Recipient resolution for the send_email universal action (spec 66).

The `to` param is a literal address unless it names an `EmailRecipient` role.
Roles need the event's target item: reporter/assignee resolve to that user's
email when the account is ACTIVE (the csat-sender idiom); `contact` goes
through the spec-62 mailintake seam — a DEFERRED, feature-detected import
(mailintake loads after automations in RADD_MODULES; module disabled = the
role never resolves). None = the engine skip-logs, same as item actions on
itemless events.
"""

import uuid
from types import ModuleType

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import service as auth_service
from radd.modules.items.models import WorkItem

from .types import EmailRecipient

MAILINTAKE_MODULE = "radd.modules.mailintake"


def _mailintake() -> ModuleType | None:
    if MAILINTAKE_MODULE not in settings.modules:
        return None
    from radd.modules.mailintake import service as mail_service

    return mail_service


async def _active_user_email(
    session: AsyncSession, user_id: uuid.UUID | None
) -> tuple[str, str] | None:
    if user_id is None:
        return None
    user = (await auth_service.users_by_ids(session, [user_id])).get(user_id)
    if user is None or not user.active:
        return None
    return user.email, user.name


async def resolve_recipient(
    session: AsyncSession, to: str, item: WorkItem | None
) -> tuple[str, str] | None:
    """(address, name) for a send_email `to` param, or None (caller skip-logs)."""
    value = to.strip()
    try:
        role = EmailRecipient(value.lower())
    except ValueError:
        return value, ""  # a literal address
    if item is None:
        return None  # role recipients need the event's target item
    match role:
        case EmailRecipient.REPORTER:
            return await _active_user_email(session, item.reporter_id)
        case EmailRecipient.ASSIGNEE:
            return await _active_user_email(session, item.assignee_id)
        case EmailRecipient.CONTACT:
            mail_service = _mailintake()
            if mail_service is None:
                return None
            contact = await mail_service.contact_for_item(session, item.id)
            return None if contact is None else (contact.email, contact.name)
