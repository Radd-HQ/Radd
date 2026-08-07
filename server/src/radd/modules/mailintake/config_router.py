"""Settings → Email's API (RADD-958).

Admin-gated CRUD over the three config tables, plus the two operations that turn
this from a form into something an operator can trust: a **test send** that
reports the Message-ID the relay actually used, and a **routing preview** that
answers "where would this land" without sending anything.

Both exist because of the same lesson from Settings → Storage: an ordered rule
chain nobody can dry-run makes "why did this go there" unanswerable, and a
credential form with no test makes "is it working" a question you can only answer
by waiting for a customer to complain.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import registry, routing
from .config_schemas import (
    MailRuleRead,
    MailRuleReorder,
    MailRuleWrite,
    MailSenderRead,
    MailSenderWrite,
    MailSourceRead,
    MailSourceWrite,
    MailTestRequest,
    MailTestResult,
    RoutingPreviewRequest,
    RoutingPreviewResult,
)
from .models import MailRule, MailSender, MailSource
from .parsing import EmailPlan
from .providers import OutboundMessage
from .senders import SmtpSender
from .types import MailEntity, MailSenderKind

router = APIRouter(prefix="/mail", tags=["mailintake"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _admin(session: AsyncSession, user) -> None:
    """Mail configuration is instance plumbing: credentials, an internet-facing
    ingest secret, and which project strangers' mail opens in. `global.manage`,
    like Storage and Sign-in — deliberately not a per-project atom."""
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)


def _source_read(row: MailSource, rule_count: int = 0) -> MailSourceRead:
    return MailSourceRead(
        id=row.id, name=row.name, kind=row.kind, enabled=row.enabled, address=row.address,
        host=row.host, port=row.port, username=row.username, folder=row.folder,
        default_project_id=row.default_project_id, has_secret=bool(row.secret),
        rule_count=rule_count,
    )


def _sender_read(row: MailSender) -> MailSenderRead:
    return MailSenderRead(
        id=row.id, name=row.name, kind=row.kind, enabled=row.enabled,
        is_default=row.is_default, from_address=row.from_address, reply_to=row.reply_to,
        host=row.host, port=row.port, username=row.username, starttls=row.starttls,
        has_secret=bool(row.secret),
    )


# --- sources -------------------------------------------------------------------


@router.get("/sources", response_model=list[MailSourceRead])
async def list_sources(session: Session, user: CurrentUser) -> list[MailSourceRead]:
    await _admin(session, user)
    out = []
    for row in await registry.list_sources(session):
        rules = await registry.list_rules(session, row.id)
        out.append(_source_read(row, len(rules)))
    return out


@router.post("/sources", response_model=MailSourceRead, status_code=201)
async def create_source(
    data: MailSourceWrite, session: Session, user: CurrentUser
) -> MailSourceRead:
    await _admin(session, user)
    row = MailSource(**data.model_dump(exclude={"secret"}), secret=data.secret or "")
    return _source_read(await registry.save_source(session, row))


@router.patch("/sources/{source_id}", response_model=MailSourceRead)
async def update_source(
    source_id: uuid.UUID, data: MailSourceWrite, session: Session, user: CurrentUser
) -> MailSourceRead:
    await _admin(session, user)
    row = await registry.get_source(session, source_id)
    for key, value in data.model_dump(exclude={"secret"}).items():
        setattr(row, key, value)
    # Omitted = unchanged, so a port edit does not require re-typing a password.
    if "secret" in data.model_fields_set and data.secret is not None:
        row.secret = data.secret
    return _source_read(await registry.save_source(session, row))


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await _admin(session, user)
    await registry.delete_source(session, source_id)


# --- senders -------------------------------------------------------------------


@router.get("/senders", response_model=list[MailSenderRead])
async def list_senders(session: Session, user: CurrentUser) -> list[MailSenderRead]:
    await _admin(session, user)
    return [_sender_read(row) for row in await registry.list_senders(session)]


@router.post("/senders", response_model=MailSenderRead, status_code=201)
async def create_sender(
    data: MailSenderWrite, session: Session, user: CurrentUser
) -> MailSenderRead:
    await _admin(session, user)
    row = MailSender(**data.model_dump(exclude={"secret"}), secret=data.secret or "")
    return _sender_read(await registry.save_sender(session, row))


@router.patch("/senders/{sender_id}", response_model=MailSenderRead)
async def update_sender(
    sender_id: uuid.UUID, data: MailSenderWrite, session: Session, user: CurrentUser
) -> MailSenderRead:
    await _admin(session, user)
    row = await registry.get_sender(session, sender_id)
    for key, value in data.model_dump(exclude={"secret"}).items():
        setattr(row, key, value)
    if "secret" in data.model_fields_set and data.secret is not None:
        row.secret = data.secret
    return _sender_read(await registry.save_sender(session, row))


@router.delete("/senders/{sender_id}", status_code=204)
async def delete_sender(sender_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await _admin(session, user)
    await registry.delete_sender(session, sender_id)


@router.post("/senders/{sender_id}/test", response_model=MailTestResult)
async def test_sender(
    sender_id: uuid.UUID, data: MailTestRequest, session: Session, user: CurrentUser
) -> MailTestResult:
    """Send one real message and report what happened.

    Returns the failure as a RESULT, not an HTTP error: "authentication failed"
    is the answer to the question the admin asked, and turning it into a 500
    would show them a generic toast instead of the relay's own words. The
    Message-ID is the one the relay reported (RADD-955) — the value threading
    actually depends on.
    """
    await _admin(session, user)
    row = await registry.get_sender(session, sender_id)
    if row.kind != MailSenderKind.SMTP.value:
        return MailTestResult(ok=False, error=f"no implementation for kind {row.kind!r}")
    try:
        message_id = await SmtpSender(row).send(
            OutboundMessage(
                to_address=data.to_address,
                subject="Radd test message",
                body=(
                    "This is a test from Settings → Email.\n\n"
                    f"Sent through {row.name} ({row.host}:{row.port}) as "
                    f"{row.from_address}.\n"
                ),
                headers={"Reply-To": row.reply_to} if row.reply_to else {},
            )
        )
        return MailTestResult(ok=True, message_id=message_id)
    except Exception as exc:  # noqa: BLE001 — the error IS the answer
        return MailTestResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:400])


# --- rules ---------------------------------------------------------------------


@router.get("/sources/{source_id}/rules", response_model=list[MailRuleRead])
async def list_rules(
    source_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[MailRuleRead]:
    await _admin(session, user)
    await registry.get_source(session, source_id)
    return [MailRuleRead.model_validate(r, from_attributes=True)
            for r in await registry.list_rules(session, source_id)]


@router.post("/sources/{source_id}/rules", response_model=MailRuleRead, status_code=201)
async def create_rule(
    source_id: uuid.UUID, data: MailRuleWrite, session: Session, user: CurrentUser
) -> MailRuleRead:
    await _admin(session, user)
    await registry.get_source(session, source_id)
    row = MailRule(
        source_id=source_id,
        name=data.name,
        rule_type=data.rule_type.value,
        enabled=data.enabled,
        config=data.config,
        project_id=data.project_id,
        position=data.position
        if data.position is not None
        else await registry.next_rule_position(session, source_id),
    )
    session.add(row)
    await session.flush()
    return MailRuleRead.model_validate(row, from_attributes=True)


@router.patch("/rules/{rule_id}", response_model=MailRuleRead)
async def update_rule(
    rule_id: uuid.UUID, data: MailRuleWrite, session: Session, user: CurrentUser
) -> MailRuleRead:
    await _admin(session, user)
    row = await session.get(MailRule, rule_id)
    if row is None:
        raise NotFoundError(MailEntity.MAIL, rule_id)
    row.name = data.name
    row.rule_type = data.rule_type.value
    row.enabled = data.enabled
    row.config = data.config
    row.project_id = data.project_id
    if data.position is not None:
        row.position = data.position
    await session.flush()
    return MailRuleRead.model_validate(row, from_attributes=True)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await _admin(session, user)
    row = await session.get(MailRule, rule_id)
    if row is not None:
        await session.delete(row)
        await session.flush()


@router.put("/sources/{source_id}/rules/order", response_model=list[MailRuleRead])
async def reorder_rules(
    source_id: uuid.UUID, data: MailRuleReorder, session: Session, user: CurrentUser
) -> list[MailRuleRead]:
    """Rewrite the whole chain's order. Sent whole because a drag is ONE intent —
    applying it as N updates leaves a half-ordered chain if one fails, and the
    order is the semantics here."""
    await _admin(session, user)
    rows = {row.id: row for row in await registry.list_rules(session, source_id)}
    for position, rule_id in enumerate(data.rule_ids, start=1):
        if rule_id in rows:
            rows[rule_id].position = float(position)
    await session.flush()
    return [MailRuleRead.model_validate(r, from_attributes=True)
            for r in await registry.list_rules(session, source_id)]


@router.post("/sources/{source_id}/preview", response_model=RoutingPreviewResult)
async def preview_routing(
    source_id: uuid.UUID, data: RoutingPreviewRequest, session: Session, user: CurrentUser
) -> RoutingPreviewResult:
    """Where would a message like this land? Nothing is created or sent."""
    await _admin(session, user)
    source = await registry.get_source(session, source_id)
    # Parse the ADDRESSES out, exactly as `parsing.extract_recipients` does for a
    # real message. Feeding the raw header text here would make the dry run
    # disagree with the live chain: `Pipeline Team <PIPELINE@radd-hq.com>` would
    # not match a rule that does match it in production — the preview would
    # report a working rule as broken, which is worse than having no preview.
    from email.utils import getaddresses, parseaddr

    plan = EmailPlan(
        subject=data.subject,
        sender_name="",
        sender_email=parseaddr(data.sender)[1].strip().lower(),
        body=data.body,
        item_key=None,
        recipients=tuple(
            address.strip().lower()
            for _, address in getaddresses([data.recipient])
            if "@" in address
        ),
    )
    decision = await routing.decide(session, plan, source_id=source_id)
    project_id = decision.project_id or source.default_project_id
    key = ""
    if project_id is not None:
        project = next(
            (p for p in await projects_service.list_projects(session) if p.id == project_id), None
        )
        key = project.key if project else ""
    return RoutingPreviewResult(
        project_id=project_id,
        project_key=key,
        matched_rule_id=decision.matched_rule_id,
        matched_rule_name=decision.matched_rule_name,
        reason=decision.reason if decision.project_id else "no rule matched — source default",
    )
