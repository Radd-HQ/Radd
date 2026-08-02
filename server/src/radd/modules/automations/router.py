import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import catalog, engine, service
from .types import MANUAL_TRIGGER, AutomationEntity
from .schemas import (
    CatalogRead,
    OperatorInfo,
    RuleCreate,
    RuleRead,
    RuleRunRequest,
    RuleRunResult,
    RuleTestRequest,
    RuleTestResult,
    RuleUpdate,
    RunnableRuleRead,
    ScheduleKindInfo,
    SubjectInfo,
    TriggerInfo,
)

router = APIRouter(prefix="/automations", tags=["automations"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Rules act on items and run as an admin system actor, so managing them is admin-level:
# AUTOMATION_MANAGE is global-scoped, held by instance admins only.
_MANAGE = authz.Permission.AUTOMATION_MANAGE


@router.get("/catalog", response_model=CatalogRead)
async def get_catalog(session: Session, user: CurrentUser) -> CatalogRead:
    """The trigger/subject/operator catalog the rule builder renders from (spec 58).
    Static per build — but served, not baked into the SPA, so extensions listing
    it stay honest about what this server supports."""
    return CatalogRead(
        triggers=[
            TriggerInfo(
                event_type=spec.event_type,
                label=spec.label,
                group=spec.group,
                item_scoped=spec.item_scoped,
                has_changes=spec.has_changes,
            )
            for spec in catalog.TRIGGERS.values()
        ],
        subjects=[
            SubjectInfo(
                key=spec.key,
                label=spec.label,
                needs_qualifier=spec.needs_qualifier,
                qualifier_hint=spec.qualifier_hint,
                requires_changes=spec.requires_changes,
            )
            for spec in catalog.SUBJECTS
        ],
        operators=[
            OperatorInfo(
                key=spec.key,
                label=spec.label,
                needs_value=spec.needs_value,
                list_value=spec.list_value,
            )
            for spec in catalog.OPERATORS
        ],
        schedule_kinds=[
            ScheduleKindInfo(key=kind, label=label) for kind, label in catalog.SCHEDULE_KINDS
        ],
    )


@router.post("", response_model=RuleRead, status_code=201)
async def create_rule(data: RuleCreate, session: Session, user: CurrentUser) -> RuleRead:
    await authz.require(session, user, authz.Permission.AUTOMATION_CREATE)
    rule = await service.create_rule(session, data, actor_id=user.id)
    return (await service.rule_reads(session, [rule]))[0]


@router.get("", response_model=list[RuleRead])
async def list_rules(session: Session, user: CurrentUser) -> list[RuleRead]:
    await authz.require(session, user, _MANAGE)
    return await service.rule_reads(session, await service.list_rules(session))


@router.get("/runnable", response_model=list[RunnableRuleRead])
async def list_runnable_rules(session: Session, user: CurrentUser) -> list[RunnableRuleRead]:
    """Enabled MANUAL rules, member-visible (item.read) — the editor `/` menu's custom
    actions. Only names leak; conditions/actions stay behind automation.manage."""
    await authz.require(session, user, authz.Permission.ITEM_READ)
    rules = await service.rules_for_trigger(session, MANUAL_TRIGGER)
    return [RunnableRuleRead.model_validate(rule) for rule in rules]


@router.patch("/{rule_id}", response_model=RuleRead)
async def update_rule(
    rule_id: uuid.UUID, data: RuleUpdate, session: Session, user: CurrentUser
) -> RuleRead:
    rule = await service.get_rule(session, rule_id)
    await authz.require(
        session, user, authz.Permission.AUTOMATION_UPDATE
    )
    rule = await service.update_rule(session, rule_id, data, actor_id=user.id)
    return (await service.rule_reads(session, [rule]))[0]


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    rule = await service.get_rule(session, rule_id)
    await authz.require(
        session, user, authz.Permission.AUTOMATION_DELETE
    )
    await service.delete_rule(session, rule_id, actor_id=user.id)


@router.post("/{rule_id}/test", response_model=RuleTestResult)
async def test_rule(
    rule_id: uuid.UUID, data: RuleTestRequest, session: Session, user: CurrentUser
) -> RuleTestResult:
    """Dry-run: which actions WOULD apply to the given item (no writes) — powers the UI preview."""
    rule = await service.get_rule(session, rule_id)
    await authz.require(session, user, _MANAGE)
    return await engine.preview(session, rule, data.item_id)


@router.post("/{rule_id}/run", response_model=RuleRunResult)
async def run_rule(
    rule_id: uuid.UUID, data: RuleRunRequest, session: Session, user: CurrentUser
) -> RuleRunResult:
    """Run a MANUAL rule on one item (the editor `/` quick-action menu). Unlike /test
    this WRITES — so it needs item.update on the item's project, not automation.manage:
    manual rules are curated by admins precisely so members can safely invoke them."""
    rule = await service.get_rule(session, rule_id)
    if rule.trigger != MANUAL_TRIGGER:
        raise ConflictError(AutomationEntity.RULE, reason="only manual rules can be run directly")
    if not rule.enabled:
        raise ConflictError(AutomationEntity.RULE, reason="rule is disabled")
    item = await items_service.require_item(session, data.item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, authz.Permission.ITEM_UPDATE, project=project)
    ran = await engine.run_manual(session, rule, data.item_id)
    return RuleRunResult(rule_id=rule.id, item_id=data.item_id, ran=ran)
