import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd import schedule as schedule_math
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import catalog, engine, samples, service
from .types import BUILTIN_OUTPUTS, AutomationEntity, AutomationTrigger
from radd.kernel.registry import registries

from . import templating

from .schemas import (
    ContributedNodeInfo,
    NodeOutputsInfo,
    OutputFieldInfo,
    EventSampleRead,
    NodeArityInfo,
    PayloadPathInfo,
    TemplateTokenInfo,
    CatalogRead,
    OperatorInfo,
    RuleCreate,
    RuleRead,
    RuleRunRequest,
    RuleRunResult,
    RuleTestRequest,
    RuleTestResult,
    RuleUpdate,
    SchedulePreviewRead,
    SchedulePreviewRequest,
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

#: Occurrences returned by the schedule preview — enough to show a PATTERN
#: (that a weekly rule really is weekly) without turning into a calendar.
_PREVIEW_RUNS = 5


def _output_info(field) -> OutputFieldInfo:
    """One `OutputField` on the wire (spec 120)."""
    return OutputFieldInfo(
        name=field.name,
        label=field.label,
        kind=field.kind,
        choices=list(field.choices),
        description=field.description,
    )


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
        contributed_nodes=[
            ContributedNodeInfo(
                key=spec.key,
                kind=spec.kind,
                label=spec.label,
                description=spec.description,
                group=spec.group,
                params_schema=spec.params_schema,
                ports=list(spec.ports),
                default_ports=list(spec.ports_at({})),
                outputs=[_output_info(field) for field in spec.outputs],
                needs_items=spec.needs_items,
                permission=spec.permission,
            )
            for spec in registries.automation_nodes.values()
        ],
        node_arity=[
            NodeArityInfo(type=node_type, default=rule.default, options=list(rule.options))
            for node_type, rule in catalog.node_arities().items()
        ],
        node_outputs=[
            NodeOutputsInfo(type=node_type, outputs=[_output_info(f) for f in fields])
            for node_type, fields in BUILTIN_OUTPUTS.items()
        ],
        can_act_as=await authz.holds(session, user, authz.Permission.AUTOMATION_ACT_AS),
        tokens=[
            TemplateTokenInfo(
                token=info.token, description=info.description, needs_item=info.needs_item
            )
            for info in templating.TOKENS
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
    """Enabled MANUAL rules, member-visible — the editor `/` menu's custom actions.
    Only names leak; conditions/actions stay behind automation.manage.

    Member floor (RADD-788): item.read in SOME project, not the global atom."""
    if not await authz.readable_projects(session, user):
        return []
    # (automation, node_id) pairs since spec 116 — a graph may hold several
    # triggers, so the engine seam returns which one matched. Validating the
    # TUPLE was a 500 on every call, and this endpoint drives the editor's `/`
    # menu, so custom quick actions silently vanished.
    rules = await service.rules_for_trigger(session, AutomationTrigger.MANUAL)
    return [RunnableRuleRead.model_validate(rule) for rule, _node_id in rules]


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
    await service.get_rule(session, rule_id)
    await authz.require(
        session, user, authz.Permission.AUTOMATION_DELETE
    )
    await service.delete_rule(session, rule_id, actor_id=user.id)



@router.post("/schedule/preview", response_model=SchedulePreviewRead)
async def preview_schedule(
    data: SchedulePreviewRequest, user: CurrentUser
) -> SchedulePreviewRead:
    """When a schedule written here would actually run (RADD-912).

    Served rather than computed in the browser because it must agree with the
    engine, and the way to guarantee that is to call the same function. A cron
    expression is unreadable without this — five fields and an OR rule nobody
    remembers — and the preview doubles as the error message: an expression that
    will be refused on save says so while it is still being typed.

    Authenticated only. It reveals arithmetic, and both automation admins and
    backup admins reach it through the same shared editor — which is also why it
    lives here rather than in `backup`: this module already owns the schedule
    vocabulary the API exposes (`catalog.schedule_kinds`). On an instance without
    `automations` loaded the backup form simply shows no preview; it does not
    fail, because the save path never depended on it.
    """
    cfg = data.model_dump(exclude_none=True)
    tz = settings.scheduler_tz
    try:
        schedule_math.validate_config(cfg)
    except ValueError as exc:
        return SchedulePreviewRead(timezone=tz, error=str(exc))

    runs: list[datetime] = []
    at = datetime.now(UTC).replace(tzinfo=None)
    for _ in range(_PREVIEW_RUNS):
        at = schedule_math.next_run(cfg, at, tz)
        runs.append(at)
    return SchedulePreviewRead(timezone=tz, next_runs=runs)

@router.get("/samples/events", response_model=EventSampleRead)
async def event_samples(
    event_type: str,
    session: Session,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> EventSampleRead:
    """What this event type actually carries, from REAL recent events (RADD-921).

    Declared BEFORE `/{rule_id}` — Starlette matches in declaration order, and a
    literal path registered after a `{uuid}` one is unreachable: it would answer
    a 422 about parsing "samples" as a UUID (see tests/test_route_shadowing.py).

    Gated on `automation.manage`, which is global-admin: a payload can name items
    from any project, and this returns them verbatim. It is the same data the
    admin audit view already serves, narrowed to one event type.
    """
    await authz.require(session, user, _MANAGE)
    if event_type not in catalog.TRIGGERS:
        raise ConflictError(
            AutomationEntity.RULE, reason=f"unknown event type {event_type!r}"
        )
    spec = catalog.TRIGGERS[event_type]
    recent = await events_service.query_events(session, event_types=[event_type], limit=limit)
    payloads = [event.payload or {} for event in recent]
    return EventSampleRead(
        event_type=event_type,
        sampled=len(payloads),
        subjects=list(spec.subjects),
        declared_schema=dict(spec.payload_schema),
        paths=[
            PayloadPathInfo(path=entry.path, examples=entry.examples, repeated=entry.repeated)
            for entry in samples.payload_paths(payloads)
        ],
        changed_fields=samples.changed_fields(payloads),
        example=payloads[0] if payloads else None,
    )


@router.post("/{rule_id}/test", response_model=RuleTestResult)
async def test_rule(
    rule_id: uuid.UUID, data: RuleTestRequest, session: Session, user: CurrentUser
) -> RuleTestResult:
    """Dry-run the graph: per node, what arrived and what left by each port, plus
    the actions it would have taken. No writes.

    `item_id` is optional — a graph fed by a search node or a schedule trigger
    has no triggering item, and demanding one made exactly those graphs the ones
    that could not be checked."""
    rule = await service.get_rule(session, rule_id)
    await authz.require(session, user, _MANAGE)
    return await engine.preview(session, rule, data.item_id, data.trigger_node_id)


@router.post("/{rule_id}/run", response_model=RuleRunResult)
async def run_rule(
    rule_id: uuid.UUID, data: RuleRunRequest, session: Session, user: CurrentUser
) -> RuleRunResult:
    """Run a MANUAL rule on one item (the editor `/` quick-action menu). Unlike /test
    this WRITES — so it needs item.update on the item's project, not automation.manage:
    manual rules are curated by admins precisely so members can safely invoke them."""
    rule = await service.get_rule(session, rule_id)
    # `rule.trigger` was a COLUMN until spec 116 made an automation a graph; the
    # read raised AttributeError, so every manual run 500'd. The trigger now
    # lives on its node, and the run must start at the manual one specifically.
    node_id = await service.manual_trigger_node(session, rule.id)
    if node_id is None:
        raise ConflictError(
            AutomationEntity.RULE, reason="only automations with a manual trigger can be run directly"
        )
    if not rule.enabled:
        raise ConflictError(AutomationEntity.RULE, reason="rule is disabled")
    item = await items_service.require_item(session, data.item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, authz.Permission.ITEM_UPDATE, project=project)
    ran = await engine.run_manual(session, rule, data.item_id, start_node_id=node_id)
    return RuleRunResult(rule_id=rule.id, item_id=data.item_id, ran=ran)
