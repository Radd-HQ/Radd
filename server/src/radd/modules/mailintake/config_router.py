"""Settings → Email's API: sources, senders, and the kind catalog (RADD-958/969).

Admin-gated CRUD over the connection rows, plus the operation that turns this
from a form into something an operator can trust: a **test send** reporting the
Message-ID the relay actually used, because a credential form with no test makes
"is it working" a question you can only answer by waiting for a customer to
complain. The routing chain and its dry run live in `rules_router`.

`GET /mail/kinds` is the spec-110 pattern (RADD-969): the add form asks the
server what a kind means instead of shipping its own copy of `smtp.gmail.com`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.kernel import changes
from radd.modules.auth.deps import CurrentUser
from radd.modules.events import service as events

from . import registry, resolve, senders
from .config_schemas import (
    MailKindInfo,
    MailKinds,
    MailSenderRead,
    MailSenderWrite,
    MailSourceRead,
    MailSourceWrite,
    MailTestRequest,
    MailTestResult,
)
from .models import MailSender, MailSource
from .providers import OutboundMessage
from .types import KIND_DEFAULTS, MailEntity, MailEvent, MailSenderKind, MailSourceKind

router = APIRouter(prefix="/mail", tags=["mailintake"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def require_mail_admin(session: AsyncSession, user) -> None:
    """Mail configuration is instance plumbing: credentials, an internet-facing
    ingest secret, and which project strangers' mail opens in. `global.manage`,
    like Storage and Sign-in — deliberately not a per-project atom.

    Public because `rules_router` gates on the same atom, and two copies of an
    authz decision is how one of them ends up different.
    """
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)


def _source_read(row: MailSource, rule_count: int = 0) -> MailSourceRead:
    return MailSourceRead(
        id=row.id, name=row.name, kind=row.kind, enabled=row.enabled, address=row.address,
        host=row.host, port=row.port, username=row.username, folder=row.folder,
        default_project_id=row.default_project_id, sender_id=row.sender_id,
        trusted_authserv_id=row.trusted_authserv_id,
        has_secret=bool(row.secret),
        rule_count=rule_count,
        resolved_host=resolve.source_host(row), resolved_port=resolve.source_port(row),
        resolved_username=resolve.source_username(row),
    )


def _sender_read(row: MailSender) -> MailSenderRead:
    return MailSenderRead(
        id=row.id, name=row.name, kind=row.kind, enabled=row.enabled,
        is_default=row.is_default, from_address=row.from_address, reply_to=row.reply_to,
        host=row.host, port=row.port, username=row.username, starttls=row.starttls,
        has_secret=bool(row.secret),
        resolved_host=resolve.sender_host(row), resolved_port=resolve.sender_port(row),
        resolved_username=resolve.sender_username(row),
        resolved_starttls=resolve.sender_starttls(row),
    )


# --- kinds ---------------------------------------------------------------------


@router.get("/kinds", response_model=MailKinds)
async def list_kinds(session: Session, user: CurrentUser) -> MailKinds:
    """What each kind answers on the operator's behalf (RADD-969).

    The spec-110 `GET /sso/kinds` shape: the form asks the server what a kind
    means rather than carrying its own copy of `smtp.gmail.com`. That copy is
    what a preset is for — one that lives on the client would have to be
    redeployed to change, which is the whole point of not hardcoding it.
    """
    await require_mail_admin(session, user)
    return MailKinds(
        sources=[_source_kind_info(kind) for kind in MailSourceKind],
        senders=[_sender_kind_info(kind) for kind in MailSenderKind],
    )


def _source_kind_info(kind: MailSourceKind) -> MailKindInfo:
    preset = KIND_DEFAULTS[kind]
    return MailKindInfo(
        kind=kind.value, name=preset.name, summary=preset.summary,
        host=preset.imap_host, port=preset.imap_port,
        guidance=preset.guidance, help_url=preset.help_url,
        preset=preset.answers_imap,
    )


def _sender_kind_info(kind: MailSenderKind) -> MailKindInfo:
    preset = KIND_DEFAULTS[kind]
    return MailKindInfo(
        kind=kind.value, name=preset.name, summary=preset.summary,
        host=preset.smtp_host, port=preset.smtp_port, starttls=preset.smtp_starttls,
        guidance=preset.guidance, help_url=preset.help_url,
        preset=preset.answers_smtp,
    )


# --- sources -------------------------------------------------------------------


@router.get("/sources", response_model=list[MailSourceRead])
async def list_sources(session: Session, user: CurrentUser) -> list[MailSourceRead]:
    await require_mail_admin(session, user)
    out = []
    for row in await registry.list_sources(session):
        rules = await registry.list_rules(session, row.id)
        out.append(_source_read(row, len(rules)))
    return out


#: Never in an event payload — a diff records that the password CHANGED, no value.
SECRET_FIELDS: tuple[str, ...] = ("secret",)


async def _emit_config(
    session: AsyncSession,
    event_type: MailEvent,
    entity_type: MailEntity,
    row: MailSource | MailSender,
    actor_id: uuid.UUID,
    diff: list[dict] | None = None,
) -> None:
    """Spec 123: mail configuration is audited with a diff."""
    await events.emit(
        session,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=row.id,
        actor_id=actor_id,
        payload={"name": row.name, "kind": row.kind},
        changes=diff,
    )


@router.post("/sources", response_model=MailSourceRead, status_code=201)
async def create_source(
    data: MailSourceWrite, session: Session, user: CurrentUser
) -> MailSourceRead:
    await require_mail_admin(session, user)
    row = MailSource(**data.model_dump(exclude={"secret"}), secret=data.secret or "")
    saved = await registry.save_source(session, row)
    await _emit_config(session, MailEvent.SOURCE_CREATED, MailEntity.SOURCE, saved, user.id)
    return _source_read(saved)


@router.patch("/sources/{source_id}", response_model=MailSourceRead)
async def update_source(
    source_id: uuid.UUID, data: MailSourceWrite, session: Session, user: CurrentUser
) -> MailSourceRead:
    await require_mail_admin(session, user)
    row = await registry.get_source(session, source_id)
    before = changes.snapshot(row, changes.column_fields(row))
    for key, value in data.model_dump(exclude={"secret"}).items():
        setattr(row, key, value)
    # Omitted = unchanged, so a port edit does not require re-typing a password.
    if "secret" in data.model_fields_set and data.secret is not None:
        row.secret = data.secret
    saved = await registry.save_source(session, row)
    await _emit_config(
        session,
        MailEvent.SOURCE_UPDATED,
        MailEntity.SOURCE,
        saved,
        user.id,
        changes.diff_object(saved, before, hidden=SECRET_FIELDS),
    )
    return _source_read(saved)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await require_mail_admin(session, user)
    row = await registry.get_source(session, source_id)
    await _emit_config(session, MailEvent.SOURCE_DELETED, MailEntity.SOURCE, row, user.id)
    await registry.delete_source(session, source_id)


# --- senders -------------------------------------------------------------------


@router.get("/senders", response_model=list[MailSenderRead])
async def list_senders(session: Session, user: CurrentUser) -> list[MailSenderRead]:
    await require_mail_admin(session, user)
    return [_sender_read(row) for row in await registry.list_senders(session)]


@router.post("/senders", response_model=MailSenderRead, status_code=201)
async def create_sender(
    data: MailSenderWrite, session: Session, user: CurrentUser
) -> MailSenderRead:
    await require_mail_admin(session, user)
    row = MailSender(**data.model_dump(exclude={"secret"}), secret=data.secret or "")
    saved = await registry.save_sender(session, row)
    await _emit_config(session, MailEvent.SENDER_CREATED, MailEntity.SENDER, saved, user.id)
    return _sender_read(saved)


@router.patch("/senders/{sender_id}", response_model=MailSenderRead)
async def update_sender(
    sender_id: uuid.UUID, data: MailSenderWrite, session: Session, user: CurrentUser
) -> MailSenderRead:
    await require_mail_admin(session, user)
    row = await registry.get_sender(session, sender_id)
    before = changes.snapshot(row, changes.column_fields(row))
    for key, value in data.model_dump(exclude={"secret"}).items():
        setattr(row, key, value)
    if "secret" in data.model_fields_set and data.secret is not None:
        row.secret = data.secret
    saved = await registry.save_sender(session, row)
    await _emit_config(
        session,
        MailEvent.SENDER_UPDATED,
        MailEntity.SENDER,
        saved,
        user.id,
        changes.diff_object(saved, before, hidden=SECRET_FIELDS),
    )
    return _sender_read(saved)


@router.delete("/senders/{sender_id}", status_code=204)
async def delete_sender(sender_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await require_mail_admin(session, user)
    row = await registry.get_sender(session, sender_id)
    await _emit_config(session, MailEvent.SENDER_DELETED, MailEntity.SENDER, row, user.id)
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
    await require_mail_admin(session, user)
    row = await registry.get_sender(session, sender_id)
    # ONE dispatch point (RADD-969) — `senders.sender_for`, the same call
    # `transport.send_item_mail` makes for every real message. When this branch
    # carried its own kind check, a kind the transport sent through answered
    # "no implementation" here.
    sender = senders.sender_for(row)
    if sender is None:
        return MailTestResult(ok=False, error=f"no implementation for kind {row.kind!r}")
    try:
        message_id = await sender.send(
            OutboundMessage(
                to_address=data.to_address,
                subject="Radd test message",
                body=(
                    "This is a test from Settings → Email.\n\n"
                    f"Sent through {row.name} "
                    f"({resolve.sender_host(row)}:{resolve.sender_port(row)}) as "
                    f"{row.from_address}.\n"
                ),
                headers={"Reply-To": row.reply_to} if row.reply_to else {},
            )
        )
        return MailTestResult(ok=True, message_id=message_id)
    except Exception as exc:  # noqa: BLE001 — the error IS the answer
        return MailTestResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:400])

