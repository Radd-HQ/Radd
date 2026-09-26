"""Settings → Email: a source's ordered ROUTING CHAIN, and its dry run — an
ordered chain nobody can dry-run makes "why did this land there" unanswerable."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import NotFoundError
from radd.kernel import changes
from radd.modules.auth.deps import CurrentUser
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service

from . import parsing, registry, routing
from .config_router import require_mail_admin
from .config_schemas import (
    MailRuleRead,
    MailRuleReorder,
    MailRuleWrite,
    RoutingPreviewRequest,
    RoutingPreviewResult,
    RoutingRuleOutcome,
)
from .models import MailRule
from .parsing import EmailPlan
from .types import MailEntity, MailEvent

router = APIRouter(prefix="/mail", tags=["mailintake"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/sources/{source_id}/rules", response_model=list[MailRuleRead])
async def list_rules(
    source_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[MailRuleRead]:
    await require_mail_admin(session, user)
    await registry.get_source(session, source_id)
    return [MailRuleRead.model_validate(r, from_attributes=True)
            for r in await registry.list_rules(session, source_id)]


async def _emit_rule(
    session: AsyncSession,
    event_type: MailEvent,
    row: MailRule,
    actor_id: uuid.UUID,
    diff: list[dict] | None = None,
) -> None:
    """Spec 123: routing rules are audited with a diff (config included — it is
    small, and WHICH project a mail lands in is the decision an auditor reads)."""
    await events.emit(
        session,
        event_type=event_type,
        entity_type=MailEntity.RULE,
        entity_id=row.id,
        actor_id=actor_id,
        payload={"name": row.name, "rule_type": row.rule_type, "source_id": str(row.source_id)},
        subjects={"project": row.project_id},
        changes=diff,
    )


@router.post("/sources/{source_id}/rules", response_model=MailRuleRead, status_code=201)
async def create_rule(
    source_id: uuid.UUID, data: MailRuleWrite, session: Session, user: CurrentUser
) -> MailRuleRead:
    await require_mail_admin(session, user)
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
    await _emit_rule(session, MailEvent.RULE_CREATED, row, user.id)
    return MailRuleRead.model_validate(row, from_attributes=True)


@router.patch("/rules/{rule_id}", response_model=MailRuleRead)
async def update_rule(
    rule_id: uuid.UUID, data: MailRuleWrite, session: Session, user: CurrentUser
) -> MailRuleRead:
    await require_mail_admin(session, user)
    row = await session.get(MailRule, rule_id)
    if row is None:
        raise NotFoundError(MailEntity.MAIL, rule_id)
    before = changes.snapshot(row, changes.column_fields(row, exclude=("id", "source_id", "created_at", "updated_at")))
    row.name = data.name
    row.rule_type = data.rule_type.value
    row.enabled = data.enabled
    row.config = data.config
    row.project_id = data.project_id
    if data.position is not None:
        row.position = data.position
    await session.flush()
    await _emit_rule(session, MailEvent.RULE_UPDATED, row, user.id, changes.diff_object(row, before))
    return MailRuleRead.model_validate(row, from_attributes=True)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await require_mail_admin(session, user)
    row = await session.get(MailRule, rule_id)
    if row is not None:
        await _emit_rule(session, MailEvent.RULE_DELETED, row, user.id)
        await session.delete(row)
        await session.flush()


@router.put("/sources/{source_id}/rules/order", response_model=list[MailRuleRead])
async def reorder_rules(
    source_id: uuid.UUID, data: MailRuleReorder, session: Session, user: CurrentUser
) -> list[MailRuleRead]:
    """Rewrite the whole chain's order — a drag is ONE intent."""
    await require_mail_admin(session, user)
    rows = {row.id: row for row in await registry.list_rules(session, source_id)}
    moved: list[tuple[MailRule, float]] = []
    for position, rule_id in enumerate(data.rule_ids, start=1):
        if rule_id in rows and rows[rule_id].position != float(position):
            moved.append((rows[rule_id], rows[rule_id].position))
            rows[rule_id].position = float(position)
    await session.flush()
    for row, previous in moved:  # spec 123: each moved rule is its own audit row
        await _emit_rule(
            session,
            MailEvent.RULE_UPDATED,
            row,
            user.id,
            [{"field": "position", "from": previous, "to": row.position}],
        )
    return [MailRuleRead.model_validate(r, from_attributes=True)
            for r in await registry.list_rules(session, source_id)]


@router.post("/sources/{source_id}/preview", response_model=RoutingPreviewResult)
async def preview_routing(
    source_id: uuid.UUID, data: RoutingPreviewRequest, session: Session, user: CurrentUser
) -> RoutingPreviewResult:
    """Where would a message like this land? Nothing is created or sent."""
    await require_mail_admin(session, user)
    source = await registry.get_source(session, source_id)
    # Parsed exactly as a live message is, or the dry run would call a working
    # rule broken.
    from email.utils import parseaddr

    plan = EmailPlan(
        subject=data.subject,
        sender_name="",
        sender_email=parseaddr(data.sender)[1].strip().lower(),
        body=data.body,
        item_key=None,
        recipients=tuple(parsing.addresses([data.recipient])),
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
        # Verbatim: `decide` knows whether a rule declined or matched with no
        # project (RADD-994); the per-rule trace shows a CRASHED rule (RADD-989).
        reason=decision.reason,
        outcomes=[
            RoutingRuleOutcome(
                rule_id=outcome.rule_id,
                rule_name=outcome.rule_name,
                status=outcome.status.value,
                detail=outcome.detail,
            )
            for outcome in decision.outcomes
        ],
    )
