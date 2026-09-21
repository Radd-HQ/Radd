"""The builder catalog as ONE read (RADD-1271).

`GET /automations/catalog` composed `CatalogRead` inline in the router, which
was fine while the SPA was its only reader. The MCP `automation_catalog` tool
needs the same answer — which nodes exist on THIS instance, what a trigger is
called, which template tokens resolve — and a second composition would drift
from the first the day a field was added to one of them. The router and the
tool both call `build`; the shape is decided once.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel.registry import registries
from radd.modules.auth import authz
from radd.modules.auth.models import User

from . import catalog, templating
from .schemas import (
    CatalogRead,
    ContributedNodeInfo,
    NodeArityInfo,
    NodeOutputsInfo,
    OperatorInfo,
    OutputFieldInfo,
    ScheduleKindInfo,
    TemplateTokenInfo,
    TriggerInfo,
)
from .types import BUILTIN_OUTPUTS


def output_info(field) -> OutputFieldInfo:
    """One `OutputField` on the wire (spec 120)."""
    return OutputFieldInfo(
        name=field.name,
        label=field.label,
        kind=field.kind,
        choices=list(field.choices),
        description=field.description,
    )


async def build(session: AsyncSession, user: User) -> CatalogRead:
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
                outputs=[output_info(field) for field in spec.outputs],
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
            NodeOutputsInfo(type=node_type, outputs=[output_info(f) for f in fields])
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
