"""The resolution notice: WHO hears that a ticket is finished, and WHAT it says
(RADD-982).

`reply.py`'s sibling, and split out for the same reason: the outbound consumer
ships both, and neither the recipient set nor the wording has anything to do
with its cursor.

**The lifecycle used to end in silence.** A requester's ticket went ack →
replies → nothing. The only message that ever said "resolved" was the CSAT
survey, which is per-project opt-in, off by default, and therefore absent on a
default install — so on the shape of instance most people run, the desk simply
stopped answering and the customer was left to guess.

Three decisions worth stating, because each rejected something:

* **It announces ENTERING done, not being done.** The guard resolves the
  diff's FROM state against the project's categories, so a done→done move —
  "Waiting for release" → "Done" is one, and spec 112's release sweep performs
  it on every shipped item — sends nothing. Matching csat's `moved_to_done`,
  which passes on that move and is saved by its unique survey row, would have
  mailed the customer twice for one resolution. Re-resolving after a REOPEN
  does announce again, deliberately: it is a new resolution, and the requester
  is the person with the least other way to learn about it. That is also why
  there is no once-per-lifetime row here — the row would buy a guarantee
  nobody wants.

* **It quotes no closing comment.** The issue asked for one "when the
  transition carried one", and in Radd a transition never does: `ItemUpdate`
  has no comment field, so the only candidate is the item's latest comment,
  which is a guess. It is also a duplicate — a public comment was already
  mailed to this exact contact by the outbound reply consumer moments earlier.
  The notice names the STATE instead, which is a fact the payload carries.

* **The subject is pinned**, like the survey's. A resolution opens a topic
  rather than continuing one, and `pin_subject` touches only the line a human
  reads: the headers a client threads on still come from the message store.
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
from .types import (
    CSAT_PLUGIN_ID,
    RESOLVED_BODY_TEMPLATE,
    RESOLVED_REASON_TEMPLATE,
    RESOLVED_SUBJECT_TEMPLATE,
    STATE_CHANGE_FIELD,
)

#: What the notice calls the state when the payload names none — a snapshot from
#: before the embed existed, or a state deleted between event and send. "Resolved"
#: is the honest generic: the category is what we actually know.
UNKNOWN_STATE = "resolved"


@dataclass(frozen=True)
class ResolvedNotice:
    """One planned resolution notice: the ticket, and everyone still outside it.

    Carries the INGREDIENTS, not a finished body — `reply.OutboundReply`'s shape,
    because the footer is a function of the recipient there and this file should
    not be the one place that stops being true.
    """

    item_id: uuid.UUID
    subject: str
    state_name: str
    item: mailrender.ItemMail
    recipients: tuple[Recipient, ...]

    #: No comment to attach, and the subject is its own sentence — see the module
    #: docstring. Class attributes rather than fields: the consumer reads them off
    #: every plan it ships, and neither is ever anything else.
    comment_id: uuid.UUID | None = None
    pin_subject: bool = True

    def render(self, recipient: Recipient) -> mailrender.RenderedMail:
        return render(self, recipient)


def _state_move(payload: dict) -> dict | None:
    """The `state` entry of this event's diff, or None when it moved no state."""
    changes = payload.get("changes") or []
    return next((c for c in changes if c.get("field") == STATE_CHANGE_FIELD), None)


def resolved_now(payload: dict) -> bool:
    """The cheap half of the guard, over the payload alone: the diff moved state
    and the NEW state (item.updated snapshots are post-mutation) is in the done
    category.

    Separate from `entered_done` because it costs nothing and `entered_done`
    costs a query: the consumer reads every `item.updated` on the stream, and
    almost none of them are a resolution.
    """
    if _state_move(payload) is None:
        return False
    state = ((payload.get("item") or {}).get("state")) or {}
    return state.get("category") == StateCategory.DONE.value


def entered_done(payload: dict, categories: Mapping[str, str]) -> bool:
    """Pure: did this `item.updated` move the item INTO the done category from
    OUTSIDE it? `categories` maps a state NAME to its category key — the diff
    records display names at write time (`items/changes.py`), which is what
    makes the record survive a rename and what forces the lookup here.

    A `from` state that no longer exists under that name resolves to nothing and
    is read as "not done", so a renamed-away state announces rather than
    swallowing a real resolution. Announcing twice is recoverable; never
    announcing is the defect this whole file exists to end.
    """
    move = _state_move(payload)
    if move is None or not resolved_now(payload):
        return False
    return categories.get(str(move.get("from") or "")) != StateCategory.DONE.value


def render(notice: ResolvedNotice, recipient: Recipient) -> mailrender.RenderedMail:
    """The text+html THIS recipient sees. Pure, so the composition tests call it
    without a database — `reply.render`'s contract."""
    body = RESOLVED_BODY_TEMPLATE.format(
        key=notice.item.key, title=notice.item.title, state=notice.state_name
    )
    return mailrender.resolution(
        notice.item,
        body=body,
        reason=RESOLVED_REASON_TEMPLATE.format(key=notice.item.key),
    )


async def _csat_announces(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """Is csat already telling this project's requesters the ticket resolved?

    The reach is DEFERRED and feature-detected (`weak_depends=("csat",)`): csat
    `depends_on` mailintake, so the edge can only run this way round, and a
    disabled or uninstalled csat must answer "no" rather than raise — the shape
    the `ai` routing rule uses (RADD-961). The precedence itself is csat's to
    state; this is only the call.
    """
    from radd.kernel import registries

    if CSAT_PLUGIN_ID not in registries.plugins:
        return False
    from radd.modules.csat import service as csat_service

    return await csat_service.announces_resolution(session, project_id)


async def plan(session: AsyncSession, event: Event) -> ResolvedNotice | None:
    """Apply the guards to one `item.updated` event; a pass returns the notice
    the consumer delivers post-commit.

    Guards in order, each one a skip the caller need not know about: the move
    entered done, the item still exists, `mail_send_resolved` resolves true for
    its project, csat is not already announcing, and somebody external is on
    the thread to tell.
    """
    payload = event.payload or {}
    if not resolved_now(payload):
        return None  # answered without touching the database — see `resolved_now`
    item_id = uuid.UUID(event.entity_id)
    try:
        item = await items.require_item(session, item_id)
    except NotFoundError:
        return None  # deleted since the event
    categories = {
        state.name: state.category
        for state in await workflow_service.list_states(session, item.project_id)
    }
    if not entered_done(payload, categories):
        return None
    enabled = await settings_service.resolve(
        session, SettingKey.MAIL_SEND_RESOLVED, project_id=item.project_id
    )
    if not enabled:
        return None
    if await _csat_announces(session, item.project_id):
        # One message, not two. The survey's own first line announces it.
        return None
    recipients = await recipients_for(session, item_id)
    if not recipients:
        return None
    project = await projects_service.get_project(session, item.project_id)
    key = f"{project.key}-{item.number}"
    state_name = ((payload.get("item") or {}).get("state") or {}).get("name") or UNKNOWN_STATE
    return ResolvedNotice(
        item_id=item_id,
        subject=RESOLVED_SUBJECT_TEMPLATE.format(key=key),
        state_name=str(state_name),
        item=mailrender.ItemMail(key=key, title=item.title, base_url=settings.app_base_url),
        recipients=recipients,
    )
