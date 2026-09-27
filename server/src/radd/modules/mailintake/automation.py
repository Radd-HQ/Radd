"""The resolution notice as an automation node (RADD-1339): `resolved.py`'s guards
and wording, minus the setting — for a rule that wants it on its own conditions."""
from dataclasses import dataclass
from typing import Any

from radd.kernel import ITEM_SUBJECT, AutomationNodeKind, AutomationNodeSpec, NodeArity
from radd.modules.items import service as items

from . import resolved, service
from .types import SentMailKind


@dataclass
class ResolutionPlan:
    detail: str
    resolves: bool = False
    notice: resolved.ResolvedNotice | None = None


async def plan_resolution(ctx: Any) -> ResolutionPlan:
    payload = ctx.packet.facts.payload
    snapshot = payload.get("item") or {}
    if not ctx.subject_ids:
        return ResolutionPlan("No issue entered a done category")
    item = await items.require_item(ctx.session, ctx.subject_ids[0])
    await items.get_item(ctx.session, item.id, ctx.actor)
    if str(item.id) != str(snapshot.get("id")):
        return ResolutionPlan("The state change belongs to another issue")
    if not await service.outbound_configured(ctx.session):
        return ResolutionPlan("Configure an outgoing email sender first")
    planned = await resolved.plan_for_item(ctx.session, item.id, payload, require_setting=False)
    return ResolutionPlan(planned.reason, planned.notice is not None, planned.notice)


async def apply_resolution(ctx: Any, plan: ResolutionPlan) -> None:
    notice = plan.notice
    if notice is None:
        return
    for recipient in notice.recipients:
        message = notice.render(recipient)
        await service.send_item_mail(
            ctx.session, item_id=notice.item_id, to_address=recipient.email, to_name=recipient.name,
            subject=notice.subject, text=message.text, html=message.html, pin_subject=True,
            kind=SentMailKind.AUTOMATION,
        )


RESOLUTION_NODE = AutomationNodeSpec(
    key="mailintake.notify_resolution", kind=AutomationNodeKind.ACTION.value, label="Notify contacts of resolution",
    group="Email", subject=ITEM_SUBJECT, arity=NodeArity.ITEM.value, reads_event=True,
    permission="item.read", params_schema={"type": "object", "properties": {}},
    description="Email all external thread contacts when an issue enters Done. Skips done-to-done changes and projects whose satisfaction survey announces resolution.",
    plan=plan_resolution, apply=apply_resolution,
)
