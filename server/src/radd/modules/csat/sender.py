"""The CSAT sender (spec 65): an outbox consumer emailing a one-click
satisfaction survey when an item RESOLVES — an `item.updated` event whose change
diff moves state and whose state embed now sits in the done category.

Cursor idiom = the shared head-seeded scaffold (`events.runner.run_head_seeded`):
consumer offset `csat.sender`, first start seeds AT THE STREAM HEAD (never
survey the historical backlog), and the cursor + survey rows + csat.requested
events commit BEFORE any email leaves — at-most-once: a dropped survey beats a
duplicate. With outbound mail or the per-project CSAT_ENABLED setting off,
events are skipped and the cursor still advances, so enabling either later
replays nothing.

Guards, in order (each one a spec-listed skip): the diff moved state into done,
CSAT_ENABLED resolves true for the item's project (scalar cascade), there is
somewhere to send FROM, the item has no survey yet (one per item LIFETIME —
reopen→re-resolve never resends), and a recipient resolves — the item's mail
contact (spec-62 seam) preferred over the reporter, when the reporter is a
person with a mailbox.

**The survey rides the ONE transport since RADD-983.** It used to gate on
`settings.smtp_host` and deliver through `radd.smtp` directly, which meant an
instance configured entirely through Settings → Email — sender ROWS, no
`RADD_SMTP_*`, which is how radd-hq.com itself is configured — never sent a
survey and said nothing about it: the guard returned None, the cursor advanced,
and no line was logged. Routing it through `mailintake.service.send_item_mail`
buys the rows-or-env sender resolution, the per-source sender identity
(RADD-979 — the survey comes from the address the ticket arrived at), threading
onto the item's own conversation, and `mail.sent`/`mail.failed`.

`pin_subject=True`, and no `comment_id`: the survey's subject is its own
sentence ("[KEY] How did we do?"), not a `Re:` on the requester's, because a
survey opens a topic rather than continuing one — but the References/In-Reply-To
headers still come from the message store, so a client files it with the ticket.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth import service as auth_service
from radd.modules.events import runner
from radd.modules.events.service import Event
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent
from radd.modules.items.models import WorkItem
from radd.modules.mailintake import service as mail_service
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.workflow.types import StateCategory

from . import service
from .types import (
    CONSUMER_NAME,
    RATING_LABELS,
    RATING_LINK_TEMPLATE,
    STATE_CHANGE_FIELD,
    SURVEY_BODY_TEMPLATE,
    SURVEY_SUBJECT_TEMPLATE,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SurveyEmail:
    #: The item being surveyed — the transport threads and resolves its sender
    #: on it, so it travels with the plan rather than being looked up again.
    item_id: uuid.UUID
    email: str
    name: str
    subject: str
    body: str


def moved_to_done(payload: dict) -> bool:
    """Pure resolve detection: the diff touched `state` AND the payload's state
    embed (the NEW state — item.updated snapshots are post-mutation) is in the
    done category. A done→done rename-move also passes, harmlessly — the unique
    survey row keeps everything once-only."""
    changes = payload.get("changes") or []
    if not any(change.get("field") == STATE_CHANGE_FIELD for change in changes):
        return False
    state = ((payload.get("item") or {}).get("state")) or {}
    return state.get("category") == StateCategory.DONE.value


def survey_body(*, key: str, title: str, token: str) -> str:
    links = "\n".join(
        RATING_LINK_TEMPLATE.format(
            label=RATING_LABELS[rating],
            base_url=settings.app_base_url,
            token=token,
            rating=rating,
        )
        for rating in sorted(RATING_LABELS)
    )
    return SURVEY_BODY_TEMPLATE.format(key=key, title=title, links=links)


async def resolve_recipient(session: AsyncSession, item: WorkItem) -> tuple[str, str] | None:
    """(email, name) — the item's mail contact (external requester, spec 62)
    preferred; else the reporter, provided they are a person with a mailbox.

    The reporter leg asks `mail_service.mailable_user` rather than
    `reporter.active` (RADD-983). An `active` check passes for a spec-113
    SERVICE account and for the system actor — and the system actor is the
    reporter of every item mail intake creates, so the accounts most likely to
    be surveyed here were exactly the two that have no mailbox. The rule is
    stated once, on the module that owns outbound mail.
    """
    contact = await mail_service.contact_for_item(session, item.id)
    if contact is not None:
        return contact.email, contact.name
    if item.reporter_id is None:
        return None
    reporter = (await auth_service.users_by_ids(session, [item.reporter_id])).get(
        item.reporter_id
    )
    if not mail_service.mailable_user(reporter):
        return None
    return reporter.email, reporter.name


async def process_event(session: AsyncSession, event: Event) -> SurveyEmail | None:
    """Apply the guards to one item.updated event. On a pass, create the survey
    row + emit csat.requested (the caller commits them with the cursor) and
    return the planned email for post-commit delivery."""
    payload = event.payload or {}
    if not moved_to_done(payload):
        return None
    item_id = uuid.UUID(event.entity_id)
    try:
        item = await items_service.require_item(session, item_id)
    except NotFoundError:
        return None  # deleted since the event
    enabled = await settings_service.resolve(
        session, SettingKey.CSAT_ENABLED, project_id=item.project_id
    )
    if not enabled:
        return None  # per-project opt-in — dev projects never send surveys
    if not await mail_service.outbound_configured(session):
        # Rows OR env (RADD-983). `settings.smtp_host` used to be this guard, so
        # a rows-only instance skipped every survey. And it skipped SILENTLY,
        # which is the half that made it unreportable — hence the line.
        logger.info(
            "csat: survey for %s skipped — no mail sender is configured", item_id
        )
        return None
    if await service.survey_for_item(session, item_id) is not None:
        return None  # one survey per item lifetime
    recipient = await resolve_recipient(session, item)
    if recipient is None:
        return None
    item_ref = payload.get("item") or {}
    key = item_ref.get("key") or str(item_id)
    title = item_ref.get("title") or ""
    survey = await service.create_survey(
        session, item_id=item_id, item_key=key
    )
    email, name = recipient
    return SurveyEmail(
        item_id=item_id,
        email=email,
        name=name,
        subject=SURVEY_SUBJECT_TEMPLATE.format(key=key),
        body=survey_body(key=key, title=title, token=survey.token),
    )


async def _plan(session: AsyncSession, event: Event) -> SurveyEmail | None:
    if event.event_type != ItemEvent.UPDATED.value:
        return None
    return await process_event(session, event)


async def _deliver_all(emails: list[SurveyEmail]) -> None:
    for email in emails:
        await _deliver(email)


async def run_once() -> int:
    return await runner.run_head_seeded(
        CONSUMER_NAME, batch_size=settings.csat_batch, plan=_plan, deliver=_deliver_all
    )


async def _deliver(email: SurveyEmail, session: AsyncSession | None = None) -> None:
    """Post-commit delivery through the ONE transport (RADD-983).

    Production passes no session: the cursor, the survey row and
    `csat.requested` are already committed by this point (at-most-once, by
    design), so there is no transaction left to join and the transport opens
    what it needs — the outbound consumer's own posture. A caller inside a
    transaction (a test) hands over its own, which is `send_ack`'s shape and
    the only way the send can be exercised against rows nobody committed.

    Still no retry queue and still never raises: a survey is a nicety, the
    survey row stays either way, and a failure is now a `mail.failed` event as
    well as a log line, so an operator can see it on Settings → Monitoring
    instead of grepping a pod.
    """
    sent = await mail_service.send_item_mail(
        session,
        item_id=email.item_id,
        to_address=email.email,
        to_name=email.name,
        subject=email.subject,
        text=email.body,
        pin_subject=True,
    )
    if sent is None:
        logger.warning("csat: survey to %s was not sent", email.email)
