"""Recipient resolution for the send_email universal action (spec 66).

The `to` param is a literal address unless it names an `EmailRecipient` role.
Roles need the event's target item: reporter/assignee resolve to that user's
email when the account is one a person reads; `contact` goes through the
spec-62 mailintake seam — a DEFERRED, feature-detected import (mailintake loads
after automations in RADD_MODULES; module disabled = the role never resolves).
None = the engine skip-logs, same as item actions on itemless events.

`mailintake_service` is public because the ENGINE needs the same seam since
RADD-983: the action's delivery goes through `send_plain_mail` now, and one
feature-detection is better than two that can disagree about whether the module
is there.
"""

import uuid
from types import ModuleType

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.items.models import WorkItem

from .types import EmailRecipient

MAILINTAKE_MODULE = "radd.modules.mailintake"


def mailintake_service() -> ModuleType | None:
    """mailintake's public seam, or None when the module is not loaded."""
    if MAILINTAKE_MODULE not in settings.modules:
        return None
    from radd.modules.mailintake import service as mail_service

    return mail_service


async def outbound_available(session: AsyncSession) -> bool:
    """Is there anywhere to send FROM? (RADD-1265)

    The planner used to answer this from the environment alone — `if not
    settings.smtp_host: skip` — which stopped being the question the moment
    RADD-983 routed delivery through the mail module's transport, where the
    DEFAULT `mail_senders` ROW comes first and the environment relay is the
    fallback. A rows-only instance (Settings → Email configured, no
    `RADD_SMTP_*`) sent every notification and skipped every automation email
    as "smtp not configured". One question, asked of the one module that knows.
    """
    mail_service = mailintake_service()
    if mail_service is None:
        return False
    return bool(await mail_service.outbound_configured(session))


PARTICIPANTS_MODULE = "radd.modules.participants"


def participants_service() -> ModuleType | None:
    """The participants module's public seam, or None when it is not loaded
    (RADD-1267: `add_participant` is feature-detected like the `contact` role).
    The service module re-exports `ParticipantAdd` so the caller needs one name."""
    if PARTICIPANTS_MODULE not in settings.modules:
        return None
    from radd.modules.participants import service as participants
    from radd.modules.participants.schemas import ParticipantAdd

    participants.ParticipantAdd = ParticipantAdd  # type: ignore[attr-defined]
    return participants


def _mailable(user: User | None) -> bool:
    """Is this account a mailbox a person reads? (RADD-983)

    Asked through the mail module, which states the rule once
    (`mailintake.service.mailable_user`): inactive, address-less, a spec-113
    SERVICE account, or the system actor — none of them somebody to email. The
    check here was `user.active` alone, so an automation addressed to
    `reporter` cheerfully mailed `automation@radd.system` on every item mail
    intake had created, and a service account's address on every item a key had
    filed. Both bounce, and a bouncing relay is what got rate-limited.

    Degrades to the old check when mailintake is absent rather than carrying a
    second copy of the rule: without that module the engine cannot send at all,
    so the strictness of a predicate on a path that skip-logs is moot.
    """
    mail_service = mailintake_service()
    if mail_service is not None:
        return bool(mail_service.mailable_user(user))
    return user is not None and user.active and bool(user.email)


async def _active_user_email(
    session: AsyncSession, user_id: uuid.UUID | None
) -> tuple[str, str] | None:
    if user_id is None:
        return None
    user = (await auth_service.users_by_ids(session, [user_id])).get(user_id)
    if not _mailable(user):
        return None
    return user.email, user.name


def is_role(value: str) -> bool:
    """Whether a `to` param names a ROLE rather than a literal address.

    Public because arity depends on it (RADD-918): a role resolves against ONE
    item, so an action addressed to `reporter` only means anything per item. The
    editor forces per-item mode when a role is chosen instead of letting someone
    build the version that skip-logs on every multi-item run — which is what
    "email each reporter" did for the whole life of the feature.
    """
    try:
        EmailRecipient(value.strip().lower())
    except ValueError:
        return False
    return True


async def resolve_user(
    session: AsyncSession, role: str, item: WorkItem | None
) -> uuid.UUID | None:
    """The USER a person-role names on `item` — for in-app notification, where
    an email address is not the identifier. `contact` is deliberately absent: a
    mail contact has no account to notify."""
    if item is None:
        return None
    match role.strip().lower():
        case EmailRecipient.REPORTER:
            return item.reporter_id
        case EmailRecipient.ASSIGNEE:
            return item.assignee_id
    return None


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
        # A role names a property of ONE item. Reaching here means the action ran
        # at SET arity over a set with no single target — the editor forces
        # per-item mode for roles, so this is the API-called path.
        return None
    match role:
        case EmailRecipient.REPORTER:
            return await _active_user_email(session, item.reporter_id)
        case EmailRecipient.ASSIGNEE:
            return await _active_user_email(session, item.assignee_id)
        case EmailRecipient.CONTACT:
            mail_service = mailintake_service()
            if mail_service is None:
                return None
            contact = await mail_service.contact_for_item(session, item.id)
            return None if contact is None else (contact.email, contact.name)
