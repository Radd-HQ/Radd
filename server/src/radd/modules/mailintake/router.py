import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import NotFoundError
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service

from . import intake, loops, parsing, service
from .schemas import MailContactRead
from .sources import webhook
from .types import MAX_BODY_BYTES, MailEntity

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mailintake"])

Session = Annotated[AsyncSession, Depends(get_session)]

#: `intake.Result` → HTTP status. The Worker turns these into SMTP outcomes, so
#: this table decides whether a sender's mail bounces or is retried (RADD-953).
#: An IGNORED message is 202 on purpose: it was received and deliberately
#: discarded, and bouncing at a mail loop puts another message into the loop.
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

    **The status codes have consequences.** They become SMTP outcomes at the
    Worker: 4xx bounces to the sender, 5xx queues and retries. So the ONLY
    failures answered with 4xx are the ones that are genuinely the message's
    fault — a bad signature, an unparseable body, an oversized one. Anything
    else propagates and becomes a 5xx, because returning 4xx for a transient
    database error silently bounces valid mail and tells the sender their
    message was rejected by policy when it was in fact dropped by an outage.

    Nothing is parsed before the signature is checked.
    """
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        # Cloudflare's own ceiling. Rejecting exactly what the provider would
        # have rejected beats inventing a second limit.
        return _status(response, 413, {"error": "message too large"})

    secret = settings.email_ingest_secret
    if not webhook.verify_signature(raw, x_radd_signature, secret):
        # Deliberately identical for "no secret configured", "no signature sent"
        # and "wrong signature": a caller learning WHICH is a caller learning
        # whether this instance is misconfigured.
        return _status(response, 401, {"error": "bad signature"})

    if not loops.limiter.allow(x_radd_envelope_from):
        # A runaway autoresponder. Dropped, not bounced — and 202, because a 4xx
        # here would generate exactly the traffic being suppressed (RADD-957).
        logger.warning("mailintake: rate limit hit for envelope sender %r", x_radd_envelope_from)
        return _status(response, 202, {"result": "ignored", "reason": "rate limited"})

    try:
        plan = parsing.parse_email(raw)
    except Exception:  # noqa: BLE001 — a message we cannot parse is the sender's problem
        logger.warning("mailintake: unparseable message from %r", x_radd_envelope_from, exc_info=True)
        return _status(response, 400, {"error": "unparseable message"})

    # Past this point every remaining failure is RADD's, not the sender's: the
    # message has already been authenticated and parsed, so there is nothing
    # left for it to be wrong about. So the catch is deliberately broad and the
    # answer is always 5xx — "when in doubt, 5xx", because 5xx queues and
    # retries while 4xx bounces.
    #
    # `ConflictError` is the one that made this necessary rather than
    # theoretical: an unset or misspelled `mail_project_key` raises it, the
    # app-wide handler maps it to 409, and the Worker would have told a customer
    # their mail was permanently rejected because of OUR configuration. Caught
    # here so it can never reach that handler.
    try:
        outcome = await intake.accept(
            session,
            plan,
            raw=raw,
            default_project_key=settings.mail_project_key,
            own_addresses=loops.own_addresses(),
            envelope_from=x_radd_envelope_from,
        )
        await session.commit()
    except Exception:  # noqa: BLE001 — see above; the status is the point
        await session.rollback()
        logger.exception(
            "mailintake: intake failed for %s — answering 5xx so the sender retries",
            plan.message_id or "(no Message-ID)",
        )
        return _status(response, 503, {"error": "intake failed; retry later"})
    if outcome.ack is not None:  # post-commit: never acknowledge a rolled-back item
        await service.send_ack(
            email=outcome.ack.email,
            name=outcome.ack.name,
            item_key=outcome.ack.item_key,
            title=outcome.ack.title,
            message_id=outcome.ack.message_id or None,
        )
    response.status_code = _RESULT_STATUS[outcome.result]
    return {"result": outcome.result.value, "item": outcome.item_key or None}


def _status(response: Response, code: int, body: dict) -> dict:
    response.status_code = code
    return body



@router.get("/items/{item_id}/mail-contact", response_model=MailContactRead)
async def item_mail_contact(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> MailContactRead:
    """The item's external requester (spec 62) — 404 when the item has none
    (most items: anything raised by a registered user)."""
    await items_service.require_readable_item(session, item_id, user)
    contact = await service.contact_for_item(session, item_id)
    if contact is None:
        raise NotFoundError(MailEntity.CONTACT, item_id)
    return MailContactRead.model_validate(contact)
