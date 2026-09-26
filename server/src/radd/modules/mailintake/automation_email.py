"""The Send email automation action, this plugin's contribution (RADD-1387) — a
disabled mail plugin takes the node out of the catalog.

`NODE_KEY` (`action.send_email`) is stored in saved graphs: never rename it.
`to` is a literal address or an `EmailRecipient` role (reporter/assignee via
`mailable_user`, or the primary mail contact); a role forces per-item arity.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.config import settings
from radd.kernel import AutomationNodeSpec, AutomationTemplateSpec
from radd.modules.auth import service as auth_service
from radd.modules.automations.types import ACTION_TYPE_PREFIX, ARITY_PARAM, NodeArity, NodePort
from radd.modules.items.models import WorkItem
from radd.modules.projects.models import Project

from . import service
from .types import EmailRecipient, SentMailKind

logger = logging.getLogger(__name__)

#: Stored in every graph that uses the action — never rename it.
NODE_KEY = f"{ACTION_TYPE_PREFIX}send_email"


class SendEmailParams(BaseModel):
    """What a Send email node stores; the engine's keys (`arity`, `act_as`) pass through."""

    # A literal address, or an `EmailRecipient` role.
    to: str = Field(min_length=1, max_length=320)
    subject: str = Field(min_length=1, max_length=500)  # template
    body: str = Field(min_length=1, max_length=10_000)  # template
    #: RADD-1318: send ON the issue's email thread, so a reply threads back. Needs an issue.
    thread: bool = False


def is_role(value: str) -> bool:
    """Whether `to` names a ROLE (which forces per-item arity, RADD-918)."""
    try:
        EmailRecipient(value.strip().lower())
    except ValueError:
        return False
    return True


async def _account_address(
    session: AsyncSession, user_id: uuid.UUID | None
) -> tuple[str, str] | None:
    if user_id is None:
        return None
    user = (await auth_service.users_by_ids(session, [user_id])).get(user_id)
    if not service.mailable_user(user):
        return None
    return user.email, user.name


async def resolve_recipient(
    session: AsyncSession, to: str, item: WorkItem | None
) -> tuple[str, str] | None:
    """(address, name) for a `to` param, or None (the node skip-logs)."""
    value = to.strip()
    try:
        role = EmailRecipient(value.lower())
    except ValueError:
        return value, ""  # a literal address
    if item is None:
        # A role names a property of ONE item; the editor forces per-item mode
        # for roles, so reaching here is the API-called path.
        return None
    match role:
        case EmailRecipient.REPORTER:
            return await _account_address(session, item.reporter_id)
        case EmailRecipient.ASSIGNEE:
            return await _account_address(session, item.assignee_id)
        case EmailRecipient.CONTACT:
            contact = await service.contact_for_item(session, item.id)
            return None if contact is None else (contact.email, contact.name)


async def deliver(
    session: AsyncSession,
    to_address: str,
    to_name: str,
    subject: str,
    body: str,
    *,
    thread_on: WorkItem | None = None,
) -> None:
    """The send, through the one transport. Itemless unless `thread_on` (RADD-1318:
    then on the issue's thread, subject pinned). Runs inside `events.automated()`,
    so its own `mail.sent` cannot re-fire the rule."""
    kind = SentMailKind.AUTOMATION
    if thread_on is None:
        sent = await service.send_plain_mail(
            session, to_address=to_address, to_name=to_name, subject=subject, text=body, kind=kind
        )
    else:
        project = await session.get(Project, thread_on.project_id)
        key = f"{project.key}-{thread_on.number}" if project is not None else ""
        rendered = mailrender.contact_notice(
            mailrender.ItemMail(key=key, title=thread_on.title, base_url=settings.app_base_url),
            body=body,
        )
        sent = await service.send_item_mail(
            session, item_id=thread_on.id, to_address=to_address, to_name=to_name,
            subject=subject, text=rendered.text, html=rendered.html, pin_subject=True, kind=kind,
        )
    if sent is None:
        logger.warning("automations: send_email to %s was not delivered", to_address)


@dataclass
class SendEmailPlan:
    """What one invocation would send; `detail`/`resolves` are the executor's report shape."""

    detail: str
    resolves: bool = False
    to_address: str = ""
    to_name: str = ""
    subject: str = ""
    body: str = ""
    thread_on: WorkItem | None = None


async def plan_send(ctx: Any) -> SendEmailPlan:
    """Resolve recipient and text — read-only, so the dry run is the real decision."""
    params = SendEmailParams.model_validate(ctx.node.params)
    if not await service.outbound_configured(ctx.session):
        # RADD-1265: asked of the transport, which knows about sender ROWS.
        return SendEmailPlan("send_email: no outbound mail sender is configured (Settings → Email)")
    item = await ctx.target_item()
    recipient = await resolve_recipient(ctx.session, await ctx.render(params.to, line=True), item)
    if recipient is None:
        return SendEmailPlan(f"send_email: no recipient resolves for {params.to!r}")
    address, name = recipient
    thread = params.thread and item is not None
    return SendEmailPlan(
        f"send_email -> {address}" + (" (on the issue's thread)" if thread else ""),
        resolves=True,
        to_address=address,
        to_name=name,
        subject=await ctx.render(params.subject, line=True),
        body=await ctx.render(params.body),
        thread_on=item if thread else None,
    )


async def apply_send(ctx: Any, plan: SendEmailPlan) -> None:
    await deliver(
        ctx.session, plan.to_address, plan.to_name, plan.subject, plan.body, thread_on=plan.thread_on
    )


def check(params: dict[str, Any]) -> None:
    """Write-time: the params model, and a ROLE recipient needs per-item arity — at
    set arity it resolves no one (RADD-918)."""
    SendEmailParams.model_validate(params)
    target = str(params.get("to") or "")
    arity = str(params.get(ARITY_PARAM) or NodeArity.SET.value)
    if is_role(target) and arity != NodeArity.ITEM.value:
        raise ValueError(
            f"{target!r} is a property of one issue, so this action must run once per "
            f"item — it would resolve no recipient otherwise. Name an address instead, "
            f"or switch it to per item."
        )


SEND_EMAIL_NODE = AutomationNodeSpec(
    key=NODE_KEY,
    kind="action",
    label="Send email",
    description="Email an address, or the issue's reporter, assignee or requester, through the outgoing mail sender.",
    group="Actions",
    keywords="send_email mail message do apply",
    params_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "maxLength": 320, "description": "An address, or reporter / assignee / contact."},
            "subject": {"type": "string", "maxLength": 500},
            "body": {"type": "string", "maxLength": 10_000},
            "thread": {"type": "boolean", "description": "Send on the issue's email thread."},
        },
    },
    default_params={"to": EmailRecipient.REPORTER.value, "subject": "", "body": ""},
    ports=(NodePort.OUT.value,),
    # A digest to a fixed address, or one mail per item — the author chooses.
    arity=NodeArity.SET.value,
    arity_options=(NodeArity.SET.value, NodeArity.ITEM.value),
    # "Nothing matched — tell me" is a fair message on an empty set.
    needs_items=False,
    plan=plan_send,
    apply=apply_send,
    check=check,
)


#: An opt-in starting point, listed exactly when Send email is (RADD-1387).
NOTIFY_REPORTER_ON_DONE = AutomationTemplateSpec(
    key="mailintake.notify_reporter_on_done",
    name="Tell the reporter when their issue is done",
    description="When an issue moves into a done state, email its reporter.",
    group="Issues",
    nodes=(
        {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.updated", "include_automated": True}},
        {"id": "done", "kind": "gate", "type": "gate.entered_state_category", "params": {"categories": ["done"]}},
        {"id": "mail", "kind": "action", "type": NODE_KEY,
         "params": {"to": EmailRecipient.REPORTER.value, ARITY_PARAM: NodeArity.ITEM.value,
                    "subject": "{{item.key}} is done",
                    "body": "Your issue {{item.key}} — {{item.title}} — is now {{item.state}}.\n{{item.url}}"}},
    ),
    edges=(
        {"source": "trg", "port": "out", "target": "done"},
        {"source": "done", "port": "true", "target": "mail"},
    ),
)
