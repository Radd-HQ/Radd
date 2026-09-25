"""Opt-in completion mail with the desk's lifecycle and recipient rules."""
from dataclasses import dataclass, field
from typing import Any
import uuid

from radd.kernel import AutomationNodeSpec, registries
from radd.modules.items import service as items
from radd.modules.projects import service as projects
from radd.modules.workflow import service as workflow
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from . import service, reply
from .types import SentMailKind


@dataclass
class ResolutionPlan:
    detail: str
    resolves: bool = False
    item_id: uuid.UUID | None = None
    subject: str = ""
    body: str = ""
    recipients: tuple[reply.Recipient, ...] = field(default_factory=tuple)


async def plan_resolution(ctx: Any) -> ResolutionPlan:
    payload = ctx.packet.facts.payload
    move = next((c for c in payload.get("changes", []) if c.get("field") == "state"), None)
    snapshot = payload.get("item") or {}
    state = snapshot.get("state") or {}
    if not move or state.get("category") != "done" or not ctx.subject_ids:
        return ResolutionPlan("No issue entered a done category")
    item = await items.require_item(ctx.session, ctx.subject_ids[0])
    await items.get_item(ctx.session, item.id, ctx.actor)
    if str(item.id) != str(snapshot.get("id")):
        return ResolutionPlan("The state change belongs to another issue")
    if not await workflow.entered_categories(ctx.session, item.project_id, payload, {"done"}):
        return ResolutionPlan("Already in a done category; no duplicate completion notice")
    if "csat" in registries.plugins and await settings_service.resolve(ctx.session, SettingKey.CSAT_ENABLED, project_id=item.project_id):
        return ResolutionPlan("The satisfaction survey announces resolution for this project")
    if not await service.outbound_configured(ctx.session):
        return ResolutionPlan("Configure an outgoing email sender first")
    recipients = await reply.recipients_for(ctx.session, item.id)
    if not recipients:
        return ResolutionPlan("No external contacts on the issue's email thread")
    project = await projects.get_project(ctx.session, item.project_id)
    key = f"{project.key}-{item.number}"
    return ResolutionPlan(
        f"Notify {len(recipients)} external contact(s) that {key} is resolved", True,
        item.id, f"[{key}] Your request has been resolved",
        f"Your request {key} — {item.title} — has been marked {state.get('name') or 'resolved'}.\n\n"
        "If it isn't sorted, reply to this email to continue the conversation.", recipients,
    )


async def apply_resolution(ctx: Any, plan: ResolutionPlan) -> None:
    for recipient in plan.recipients:
        await service.send_item_mail(ctx.session, item_id=plan.item_id,
            to_address=recipient.email, to_name=recipient.name, subject=plan.subject,
            text=plan.body, pin_subject=True, kind=SentMailKind.AUTOMATION)


RESOLUTION_NODE = AutomationNodeSpec(
    key="mailintake.notify_resolution", kind="action", label="Notify contacts of resolution",
    group="Email", subject="item", arity="item", reads_event=True,
    permission="item.read", params_schema={"type": "object", "properties": {}},
    description="Email all external thread contacts when an issue enters Done. Skips done-to-done changes and projects whose satisfaction survey announces resolution.",
    plan=plan_resolution, apply=apply_resolution,
)
