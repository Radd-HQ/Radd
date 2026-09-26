"""The resolution notice: WHO hears that a ticket is finished, and WHAT it says
(RADD-982/1368). Shared by the outbound consumer (`mail_send_resolved`) and the
`mailintake.notify_resolution` node, so guards and wording cannot drift.

* It announces ENTERING done: a done→done move (the release sweep's "Waiting
  for release" → "Done") sends nothing; a re-resolution after a reopen does.
* It quotes no closing comment: the reply relay already mailed any public one.
* The subject is pinned, like the survey's: a resolution opens a topic.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.events.service import Event
from radd.modules.items import service as items
from radd.modules.projects import service as projects_service
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow.types import StateCategory

from .reply import Recipient, recipients_for
from .transport import MailAttachment
from .types import (
    CSAT_PLUGIN_ID,
    RESOLVED_BODY_TEMPLATE,
    RESOLVED_REASON_TEMPLATE,
    RESOLVED_SUBJECT_TEMPLATE,
    STATE_CHANGE_FIELD,
    SentMailKind,
)

#: What the notice calls the state when the payload names none — the category is
#: what we actually know.
UNKNOWN_STATE = "resolved"


@dataclass(frozen=True)
class ResolvedNotice:
    """One planned resolution notice — ingredients, like `reply.OutboundReply`."""

    item_id: uuid.UUID
    subject: str
    state_name: str
    item: mailrender.ItemMail
    recipients: tuple[Recipient, ...]

    comment_id: uuid.UUID | None = None
    pin_subject: bool = True
    kind: SentMailKind = SentMailKind.RESOLUTION

    async def prepare(self, session: AsyncSession) -> tuple["ResolvedNotice", tuple[MailAttachment, ...]]:
        """Nothing to re-read: the notice is composed from the event alone."""
        del session
        return self, ()

    def render(self, recipient: Recipient) -> mailrender.RenderedMail:
        return render(self, recipient)


@dataclass(frozen=True)
class Planned:
    """A notice, or why there is none — the node shows the reason in a dry run."""

    notice: ResolvedNotice | None
    reason: str


def _state_move(payload: dict) -> dict | None:
    changes = payload.get("changes") or []
    return next((c for c in changes if c.get("field") == STATE_CHANGE_FIELD), None)


def resolved_now(payload: dict) -> bool:
    """The cheap half of the guard, over the payload alone: the diff moved state
    and the NEW state is in the done category. Separate from `entered_done`
    because the consumer reads every `item.updated`, and almost none of them
    are a resolution."""
    if _state_move(payload) is None:
        return False
    state = ((payload.get("item") or {}).get("state")) or {}
    return state.get("category") == StateCategory.DONE.value


def entered_done(payload: dict, categories: Mapping[str, str]) -> bool:
    """Pure: did this `item.updated` move the item INTO done from OUTSIDE it?
    `categories` maps a state NAME to its category — the diff records display
    names. A `from` state renamed away reads as "not done", so a real
    resolution is announced rather than swallowed."""
    move = _state_move(payload)
    if move is None or not resolved_now(payload):
        return False
    return categories.get(str(move.get("from") or "")) != StateCategory.DONE.value


def render(notice: ResolvedNotice, recipient: Recipient) -> mailrender.RenderedMail:
    """Pure, so the composition tests call it without a database."""
    del recipient  # one wording for every contact on the thread
    body = RESOLVED_BODY_TEMPLATE.format(
        key=notice.item.key, title=notice.item.title, state=notice.state_name
    )
    return mailrender.contact_notice(
        notice.item, body=body, reason=RESOLVED_REASON_TEMPLATE.format(key=notice.item.key)
    )


async def _csat_announces(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """Is the satisfaction survey already telling this project's requesters?
    Deferred and feature-detected (`weak_depends=("csat",)`): csat depends on
    this module, and a disabled csat answers "no" by absence."""
    from radd.kernel import registries

    if CSAT_PLUGIN_ID not in registries.plugins:
        return False
    from radd.modules.csat import service as csat_service

    return await csat_service.announces_resolution(session, project_id)


async def plan_for_item(
    session: AsyncSession, item_id: uuid.UUID, payload: dict, *, require_setting: bool
) -> Planned:
    """Apply the guards to one `item.updated` payload about `item_id`.

    In order: the move entered done, the item still exists, (`require_setting`)
    `mail_send_resolved` is on for its project, csat is not already announcing,
    and somebody external is on the thread to tell."""
    if not resolved_now(payload):
        return Planned(None, "No issue entered a done category")
    try:
        item = await items.require_item(session, item_id)
    except NotFoundError:
        return Planned(None, "The issue no longer exists")
    categories = {
        state.name: state.category
        for state in await workflow_service.list_states(session, item.project_id)
    }
    if not entered_done(payload, categories):
        return Planned(None, "Already in a done category; no duplicate notice")
    if require_setting and not await settings_service.resolve(
        session, SettingKey.MAIL_SEND_RESOLVED, project_id=item.project_id
    ):
        return Planned(None, "Resolution notices are off for this project")
    if await _csat_announces(session, item.project_id):
        return Planned(None, "The satisfaction survey announces resolution for this project")
    recipients = await recipients_for(session, item_id)
    if not recipients:
        return Planned(None, "No external contacts on the issue's email thread")
    project = await projects_service.get_project(session, item.project_id)
    key = f"{project.key}-{item.number}"
    state_name = ((payload.get("item") or {}).get("state") or {}).get("name") or UNKNOWN_STATE
    notice = ResolvedNotice(
        item_id=item_id,
        subject=RESOLVED_SUBJECT_TEMPLATE.format(key=key),
        state_name=str(state_name),
        item=mailrender.ItemMail(key=key, title=item.title, base_url=settings.app_base_url),
        recipients=recipients,
    )
    return Planned(notice, f"Notify {len(recipients)} external contact(s) that {key} is resolved")


async def plan(session: AsyncSession, event: Event) -> ResolvedNotice | None:
    """The consumer's planner: the notice this `item.updated` earns under the
    `mail_send_resolved` setting, or None."""
    payload = event.payload or {}
    if not resolved_now(payload):
        return None  # answered without touching the database
    planned = await plan_for_item(session, uuid.UUID(event.entity_id), payload, require_setting=True)
    return planned.notice
