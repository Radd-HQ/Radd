import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.attachments import service as attachments_service
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service

from . import intake, loops, parsing, registry, service
from .models import MailMessage
from .schemas import MailContactRead
from .sources import webhook
from .transport import MailHealth
from .types import MAX_BODY_BYTES, RAW_MESSAGE_CONTENT_TYPE, RAW_MESSAGE_FILENAME, MailEntity

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mailintake"])

Session = Annotated[AsyncSession, Depends(get_session)]

#: `intake.Result` → HTTP status, which the Worker turns into SMTP outcomes
#: (RADD-953). IGNORED is 202: bouncing at a mail loop feeds the loop.
_RESULT_STATUS = {
    intake.Result.CREATED: 202,
    intake.Result.APPENDED: 202,
    intake.Result.IGNORED: 202,
    intake.Result.DUPLICATE: 200,
}


@router.post("/integrations/email")
async def ingest_email(
    request: Request,
    session: Session,
    response: Response,
    x_radd_signature: Annotated[str, Header()] = "",
    x_radd_envelope_from: Annotated[str, Header()] = "",
    x_radd_envelope_to: Annotated[str, Header()] = "",
) -> dict:
    """Accept one raw RFC822 message from a mail source (RADD-953).

    The status becomes an SMTP outcome at the Worker: 4xx bounces, 5xx retries.
    Only the message's own faults (signature, size, unparseable) answer 4xx;
    everything else is 5xx. Nothing is parsed before the signature is checked.
    """
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return _status(response, 413, {"error": "message too large"})

    # The SOURCE row (by envelope recipient) decides the secret and the routing
    # (RADD-958); the env secret only while no row exists.
    source = await registry.source_for_address(session, x_radd_envelope_to)
    secret = source.secret if source is not None else settings.email_ingest_secret
    if not webhook.verify_signature(raw, x_radd_signature, secret):
        # Identical for no secret, no signature and a wrong one: which one it was
        # would tell a caller whether this instance is misconfigured.
        return _status(response, 401, {"error": "bad signature"})

    if not loops.limiter.allow(x_radd_envelope_from):
        # A runaway autoresponder: 202, because a bounce feeds it (RADD-957).
        logger.warning("mailintake: rate limit hit for envelope sender %r", x_radd_envelope_from)
        return _status(response, 202, {"result": "ignored", "reason": "rate limited"})

    try:
        plan = parsing.parse_email(raw)
    except Exception:  # noqa: BLE001 — a message we cannot parse is the sender's problem
        logger.warning("mailintake: unparseable message from %r", x_radd_envelope_from, exc_info=True)
        return _status(response, 400, {"error": "unparseable message"})

    # Past here every failure is Radd's, not the sender's — answer 5xx so the
    # relay retries. ConflictError from a bad default project must not reach the
    # 409 handler.
    try:
        outcome = await intake.accept(
            session,
            plan,
            raw=raw,
            default_project_key=settings.mail_project_key,
            own_addresses=await registry.own_addresses(session),
            envelope_from=x_radd_envelope_from,
            source_id=source.id if source is not None else None,
            default_project_id=source.default_project_id if source is not None else None,
        )
        await session.commit()
    except Exception:  # noqa: BLE001 — see above; the status is the point
        await session.rollback()
        logger.exception(
            "mailintake: intake failed for %s — answering 5xx so the sender retries",
            plan.message_id or "(no Message-ID)",
        )
        return _status(response, 503, {"error": "intake failed; retry later"})
    # Post-commit: never acknowledge a rolled-back item, and the receipt's
    # In-Reply-To reads the committed inbound id.
    if outcome.ack is not None:
        await service.send_ack(outcome.ack)
    response.status_code = _RESULT_STATUS[outcome.result]
    return {"result": outcome.result.value, "item": outcome.item_key or None}


def _status(response: Response, code: int, body: dict) -> dict:
    response.status_code = code
    return body



@router.get("/items/{item_id}/mail-contacts", response_model=list[MailContactRead])
async def item_mail_contacts(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[MailContactRead]:
    """Everyone external on the item's mail thread, primary first (RADD-980); an
    empty list, never a 404."""
    await items_service.require_readable_item(session, item_id, user)
    return [
        MailContactRead.model_validate(contact)
        for contact in await service.contacts_for_item(session, item_id)
    ]


@router.get("/items/{item_id}/mail-contact", response_model=MailContactRead)
async def item_mail_contact(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> MailContactRead:
    """The item's PRIMARY external requester (spec 62) — 404 when it has none. Kept
    singular as it shipped: a contract with clients this repo does not build."""
    await items_service.require_readable_item(session, item_id, user)
    contact = await service.contact_for_item(session, item_id)
    if contact is None:
        raise NotFoundError(MailEntity.CONTACT, item_id)
    return MailContactRead.model_validate(contact)


@router.get("/mail/messages/{message_row_id}/raw")
async def mail_message_raw(
    message_row_id: uuid.UUID, session: Session, user: CurrentUser
) -> Response:
    """Retained raw bytes of one inbound message (RADD-1033), behind the item's read
    gate. Unknown id and "nothing retained" are the same 404."""
    row = await session.get(MailMessage, message_row_id)
    if row is None or not row.raw_storage_name:
        raise NotFoundError(MailEntity.MESSAGE, message_row_id)
    await items_service.require_readable_item(session, row.item_id, user)
    data = await attachments_service.read_blob(
        session, row.raw_storage_name, host_id=row.raw_host_id
    )
    return Response(
        content=data,
        media_type=RAW_MESSAGE_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{RAW_MESSAGE_FILENAME}"'},
    )


@router.get("/mail/health", response_model=MailHealth)
async def outbound_health(session: Session, user: CurrentUser) -> MailHealth:
    """Operator-only delivery health, owned by the plugin that sends the mail."""
    if not authz.is_instance_admin(user):
        raise ForbiddenError("mail health requires an instance admin")
    return await service.mail_health(session)
