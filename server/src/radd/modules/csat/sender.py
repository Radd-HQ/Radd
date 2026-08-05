"""The CSAT sender (spec 65): an outbox consumer emailing a one-click
satisfaction survey when an item RESOLVES — an `item.updated` event whose change
diff moves state and whose state embed now sits in the done category.

Cursor idiom = the shared head-seeded scaffold (`events.runner.run_head_seeded`):
consumer offset `csat.sender`, first start seeds AT THE STREAM HEAD (never
survey the historical backlog), and the cursor + survey rows + csat.requested
events commit BEFORE any email leaves — at-most-once: a dropped survey beats a
duplicate. With SMTP or the per-project CSAT_ENABLED setting off, events are
skipped and the cursor still advances, so enabling either later replays nothing.

Guards, in order (each one a spec-listed skip): the diff moved state into done,
CSAT_ENABLED resolves true for the item's project (scalar cascade), SMTP is
configured, the item has no survey yet (one per item LIFETIME — reopen→
re-resolve never resends), and a recipient resolves — the item's mail contact
(spec-62 seam) preferred over the reporter's active-user email.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd import smtp
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
    BATCH,
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
    state = payload.get("state") or {}
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
    preferred; else the reporter, provided they are an ACTIVE user."""
    contact = await mail_service.contact_for_item(session, item.id)
    if contact is not None:
        return contact.email, contact.name
    if item.reporter_id is None:
        return None
    reporter = (await auth_service.users_by_ids(session, [item.reporter_id])).get(
        item.reporter_id
    )
    if reporter is None or not reporter.active:
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
    if not settings.smtp_host:
        return None
    if await service.survey_for_item(session, item_id) is not None:
        return None  # one survey per item lifetime
    recipient = await resolve_recipient(session, item)
    if recipient is None:
        return None
    key = payload.get("key") or str(item_id)
    title = payload.get("title") or ""
    survey = await service.create_survey(
        session, item_id=item_id, item_key=key
    )
    email, name = recipient
    return SurveyEmail(
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
        CONSUMER_NAME, batch_size=BATCH, plan=_plan, deliver=_deliver_all
    )


async def _deliver(email: SurveyEmail) -> None:
    try:
        await asyncio.to_thread(
            smtp.send_message, email.email, email.subject, email.body, to_name=email.name
        )
    except Exception:
        # Log + move on (googlechat/mailintake precedent) — the survey row stays,
        # so the item is simply never surveyed; no retry queue for a nicety mail.
        logger.exception("csat: survey send to %s failed (dropped)", email.email)
