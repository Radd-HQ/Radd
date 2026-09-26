import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.schedule_preview import SchedulePreviewRead, SchedulePreviewRequest, preview_schedule as schedule_preview
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.events import service as events_service
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import catalog, engine, graph, runs, samples, service, templates, versions
from .types import AutomationEntity, AutomationTrigger
from radd.kernel.registry import registries

from . import templating

from .schemas import (
    AutomationTemplateRead,
    NodeInfo,
    NodeShapeRead,
    NodeShapeRequest,
    TriggerKindInfo,
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
    RestoreRequest,
    RunDetailRead,
    RunRead,
    VersionDetailRead,
    VersionRead,
    RunnableRuleRead,
    ScheduleKindInfo,
    TriggerInfo,
)

router = APIRouter(prefix="/automations", tags=["automations"])

Session = Annotated[AsyncSession, Depends(get_session)]

# automation.manage is global: an automation acts on any project's items.
_MANAGE = authz.Permission.AUTOMATION_MANAGE

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
    """The builder catalog: triggers, operators, node types, trigger kinds, arity
    rules and tokens — live from the registries of the installed plugins."""
    node_owners = {
        node.key: plugin.name
        for plugin in registries.plugins.values()
        for node in plugin.automation_nodes
    }
    event_owners = registries.event_owners()
    return CatalogRead(
        max_chain_depth=settings.automation_max_chain_depth,
        triggers=[
            TriggerInfo(
                event_type=spec.event_type,
                plugin=event_owners[str(spec.event_type)],
                label=spec.label,
                group=spec.group,
                item_scoped=spec.item_scoped,
                has_changes=spec.has_changes,
            )
            for spec in catalog.triggers().values()
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
        nodes=[
            NodeInfo(
                key=spec.key,
                plugin=node_owners[spec.key],
                kind=spec.kind,
                label=spec.label,
                description=spec.description,
                group=spec.group,
                params_schema=spec.params_schema,
                keywords=spec.keywords,
                default_params=dict(spec.default_params),
                reads_event=spec.reads_event,
                produces_findings=spec.produces_findings,
                dynamic_ports=spec.dynamic_ports,
                terminal=spec.terminal,
                dynamic_outputs=spec.dynamic_outputs,
                shape_params=list(spec.shape_params) if spec.shape_params is not None else None,
                ports=list(spec.ports),
                default_ports=list(spec.ports_at(spec.default_params or {})),
                outputs=[_output_info(field) for field in spec.outputs],
                needs_items=spec.needs_items,
                permission=spec.permission,
            )
            for spec in registries.automation_nodes.values()
        ],
        trigger_kinds=[
            TriggerKindInfo(
                key=kind.key,
                label=kind.label,
                group=kind.group,
                description=kind.description,
                params_schema=kind.params_schema,
                default_params=dict(kind.default_params),
                has_event=kind.has_event,
                seeds=list(kind.seeds),
            )
            for kind in registries.trigger_kinds.values()
        ],
        node_arity=[
            NodeArityInfo(type=node_type, default=rule.default, options=list(rule.options))
            for node_type, rule in catalog.node_arities().items()
        ],
        can_act_as=await authz.holds(session, user, authz.Permission.AUTOMATION_ACT_AS),
        tokens=[
            TemplateTokenInfo(
                token=info.token, description=info.description, needs_item=info.needs_item
            )
            for info in templating.all_tokens()
        ],
    )


@router.get("/templates", response_model=list[AutomationTemplateRead])
async def list_templates(session: Session, user: CurrentUser) -> list[AutomationTemplateRead]:
    """Whole automations offered as starting points (RADD-1316), from every
    loaded plugin. One that names a node type or trigger event this instance
    does not offer is left out, so what is listed can be opened and saved."""
    await authz.require(session, user, authz.Permission.AUTOMATION_CREATE)
    return [
        AutomationTemplateRead(
            key=template.key,
            plugin=plugin.name,
            name=template.name,
            description=template.description,
            group=template.group,
            nodes=[dict(node) for node in template.nodes],
            edges=[dict(edge) for edge in template.edges],
        )
        for plugin in registries.plugins.values()
        for template in plugin.automation_templates
        if templates.available(template)
    ]


@router.post("/nodes/{node_type}/shape", response_model=NodeShapeRead)
async def node_shape(node_type: str, data: NodeShapeRequest, user: CurrentUser) -> NodeShapeRead:
    """A node's ports and outputs for the given params (RADD-1325) — the one
    answer `graph.validate` checks edges against, served so the canvas never
    has to recompute it. Pure: no session, nothing stored."""
    from radd.exceptions import NotFoundError

    spec = registries.automation_nodes.get(node_type)
    if spec is None:
        raise NotFoundError(AutomationEntity.RULE, node_type)
    return NodeShapeRead(
        ports=list(spec.ports_at(data.params)),
        outputs=[_output_info(field) for field in spec.outputs_at(data.params)],
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
    # (automation, node_id) pairs since spec 116 — a graph may hold several triggers.
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
    """Authenticated arithmetic preview for an automation draft."""
    return schedule_preview(data, settings.scheduler_tz)


@router.get("/samples/events", response_model=EventSampleRead)
async def event_samples(
    event_type: str,
    session: Session,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> EventSampleRead:
    """What this event type carries, from REAL recent events (RADD-921). Declared
    before `/{rule_id}` (route order). automation.manage: payloads name items from
    any project."""
    await authz.require(session, user, _MANAGE)
    spec = catalog.triggers().get(event_type)
    if spec is None:
        raise ConflictError(
            AutomationEntity.RULE, reason=f"unknown event type {event_type!r}"
        )
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
        declared_paths=await _declared_paths(session, spec),
    )


async def _declared_paths(session: AsyncSession, spec) -> list[PayloadPathInfo]:
    """RADD-1331: the declared shape for an event that has not fired here yet —
    the payload schema's paths, and each subject's ref fields taken from a REAL
    ref of that type (its values become the examples). A subject never seen on
    this instance still lists its own name."""
    found: dict[str, PayloadPathInfo] = {}
    for subject in spec.subjects:
        ref = await events_service.latest_ref(session, subject)
        entries = samples.payload_paths([{subject: ref}]) if ref else [samples.PayloadPath(path=f"{subject}.id")]
        for entry in entries:
            found.setdefault(entry.path, PayloadPathInfo(path=entry.path, examples=entry.examples, repeated=entry.repeated))
    for entry in samples.schema_paths(dict(spec.payload_schema)):
        found.setdefault(entry.path, PayloadPathInfo(path=entry.path, repeated=entry.repeated))
    return sorted(found.values(), key=lambda info: info.path)


@router.get("/samples/records")
async def recorded_samples(event_type: str, session: Session, user: CurrentUser) -> list[dict]:
    from sqlalchemy import select
    await authz.require(session, user, _MANAGE)
    rows = await session.scalars(select(events_service.Event).where(events_service.Event.event_type == event_type)
                                .order_by(events_service.Event.id.desc()).limit(20))
    return [{"id": row.id, "created_at": row.created_at, "payload": row.payload} for row in rows]


async def _preview_draft(data: RuleTestRequest, session: Session, user: CurrentUser, rule=None):
    from types import SimpleNamespace
    await authz.require(session, user, _MANAGE)
    if data.nodes is not None:
        nodes = [n.model_dump(mode="json") for n in data.nodes]
        edges = [e.model_dump(mode="json") for e in data.edges or []]
        await service._validate_graph(session, nodes, edges, user.id)
        rule = SimpleNamespace(id=rule.id if rule else uuid.uuid4(), name=data.name, nodes=nodes, edges=edges,
                               created_by_id=rule.created_by_id if rule else user.id)
    if rule is None:
        raise ConflictError("automation", reason="Provide a graph to preview")
    if data.subject_id is not None and data.subject != graph.ITEM_SUBJECT:
        await _require_seedable(session, data.subject, data.subject_id)
    try:
        return await engine.preview(session, rule, data.item_id or (data.subject_id if data.subject == graph.ITEM_SUBJECT else None),
            data.trigger_node_id, subject=data.subject, subject_id=data.subject_id,
            event_id=data.event_id, event_payload=data.event_payload, project_id=data.project_id)
    except ValueError as exc:
        raise ConflictError("automation", reason=str(exc)) from exc


@router.post("/preview", response_model=RuleTestResult)
async def preview_draft(data: RuleTestRequest, session: Session, user: CurrentUser) -> RuleTestResult:
    return await _preview_draft(data, session, user)


@router.post("/{rule_id}/test", response_model=RuleTestResult)
async def test_rule(rule_id: uuid.UUID, data: RuleTestRequest, session: Session, user: CurrentUser) -> RuleTestResult:
    return await _preview_draft(data, session, user, await service.get_rule(session, rule_id))


@router.get("/{rule_id}/versions", response_model=list[VersionRead])
async def list_versions(rule_id: uuid.UUID, session: Session, user: CurrentUser) -> list[VersionRead]:
    """Every version, newest first (RADD-1268)."""
    rule = await service.get_rule(session, rule_id)
    await authz.require(session, user, _MANAGE)
    return await service.version_reads(session, await versions.list_versions(session, rule.id))


@router.get("/{rule_id}/versions/{version}", response_model=VersionDetailRead)
async def get_version(
    rule_id: uuid.UUID, version: int, session: Session, user: CurrentUser
) -> VersionDetailRead:
    """One version with its graph, for the read-only preview."""
    rule = await service.get_rule(session, rule_id)
    await authz.require(session, user, _MANAGE)
    row = await versions.get_version(session, rule.id, version)
    read = (await service.version_reads(session, [row]))[0]
    return VersionDetailRead(
        **read.model_dump(), nodes=row.nodes or [], edges=row.edges or [], orientation=row.orientation
    )


@router.post("/{rule_id}/versions/{version}/restore", response_model=RuleRead)
async def restore_version(
    rule_id: uuid.UUID, version: int, data: RestoreRequest, session: Session, user: CurrentUser
) -> RuleRead:
    """Make `version` current by writing a NEW version that copies it."""
    await service.get_rule(session, rule_id)
    await authz.require(session, user, _MANAGE)
    rule = await service.restore_version(session, rule_id, version, user.id, note=data.note)
    return (await service.rule_reads(session, [rule]))[0]


@router.get("/{rule_id}/runs", response_model=list[RunRead])
async def list_runs(
    rule_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    limit: int = 50,
    before: datetime | None = None,
) -> list[RunRead]:
    """Recorded runs, newest first (RADD-1266). `before` pages by `started_at`."""
    rule = await service.get_rule(session, rule_id)
    await authz.require(session, user, _MANAGE)
    rows = await runs.list_runs(session, rule.id, limit=limit, before=before)
    return [RunRead.model_validate(row) for row in rows]


@router.get("/{rule_id}/runs/{run_id}", response_model=RunDetailRead)
async def get_run(
    rule_id: uuid.UUID, run_id: uuid.UUID, session: Session, user: CurrentUser
) -> RunDetailRead:
    """One run with its whole report — the dry run's shape."""
    rule = await service.get_rule(session, rule_id)
    await authz.require(session, user, _MANAGE)
    row = await runs.get_run(session, rule.id, run_id)
    read = RunDetailRead.model_validate(row)
    read.report = RuleTestResult.model_validate(row.report) if row.report else None
    return read


@router.post("/{rule_id}/run", response_model=RuleRunResult)
async def run_rule(
    rule_id: uuid.UUID, data: RuleRunRequest, session: Session, user: CurrentUser
) -> RuleRunResult:
    """Run a MANUAL rule on one item (the editor `/` quick-action menu). Unlike /test
    this WRITES — so it needs item.update on the item's project, not automation.manage:
    manual rules are curated by admins precisely so members can safely invoke them."""
    rule = await service.get_rule(session, rule_id)
    # The run starts at the MANUAL trigger node specifically.
    node_id = await service.manual_trigger_node(session, rule.id)
    if node_id is None:
        raise ConflictError(
            AutomationEntity.RULE, reason="only automations with a manual trigger can be run directly"
        )
    if not rule.enabled:
        raise ConflictError(AutomationEntity.RULE, reason="rule is disabled")
    subject, subject_id = _seed_of(data.item_id, data.subject, data.subject_id)
    if subject == graph.ITEM_SUBJECT:
        item = await items_service.require_item(session, subject_id)
        project = await projects_service.get_project(session, item.project_id)
        await authz.require(session, user, authz.Permission.ITEM_UPDATE, project=project)
    else:
        # RADD-1323: another subject (a page). No generic per-entity write atom
        # exists to check against, so this is the automation managers' button.
        await _require_seedable(session, subject, subject_id)
        await authz.require(session, user, authz.Permission.AUTOMATION_MANAGE)
    ran = await engine.run_manual(session, rule, subject_id, start_node_id=node_id, subject=subject)
    return RuleRunResult(
        rule_id=rule.id,
        item_id=subject_id if subject == graph.ITEM_SUBJECT else None,
        subject=subject,
        subject_id=subject_id,
        ran=ran,
    )


def _seed_of(item_id, subject: str, subject_id) -> tuple[str, uuid.UUID]:
    """The one subject a manual run or dry run starts from: `item_id` (the
    original field) or `subject` + `subject_id` (RADD-1323)."""
    if subject_id is None and item_id is not None:
        return "item", item_id
    if subject_id is None:
        raise ConflictError(
            AutomationEntity.RULE, reason="name what to run on: item_id, or subject and subject_id"
        )
    return subject, subject_id


async def _require_seedable(session, subject: str, subject_id: uuid.UUID) -> None:
    """The manual kind must offer this subject, and the id must resolve."""
    from radd.kernel.registry import registries

    from .types import AutomationTrigger

    kind = registries.trigger_kinds.get(AutomationTrigger.MANUAL.value)
    ref = registries.entity_refs.get(subject)
    if kind is None or subject not in kind.seeds or ref is None:
        raise ConflictError(AutomationEntity.RULE, reason=f"a manual run cannot start from a {subject!r}")
    if await ref.ref(session, subject_id) is None:
        raise ConflictError(AutomationEntity.RULE, reason=f"no {subject} {subject_id}")
